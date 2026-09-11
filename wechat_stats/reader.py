"""从解密后的微信数据库读取消息。"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from wechat_stats.types import type_label

try:
    import zstandard as zstd

    _ZSTD_DECODER = zstd.ZstdDecompressor()
except Exception:
    _ZSTD_DECODER = None

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


@dataclass
class Contact:
    username: str
    display_name: str
    remark: str
    nick_name: str
    is_group: bool


@dataclass
class Message:
    local_id: int
    local_type: int
    type_name: str
    create_time: int
    is_sender: bool
    text: str = ""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def load_contacts(decrypted_dir: Path) -> dict[str, Contact]:
    contact_db = decrypted_dir / "contact" / "contact.db"
    if not contact_db.exists():
        return {}

    contacts: dict[str, Contact] = {}
    with _connect(contact_db) as con:
        if not _table_exists(con, "contact"):
            return {}
        for row in con.execute("SELECT * FROM contact"):
            item = dict(row)
            username = str(item.get("username") or item.get("userName") or "")
            if not username:
                continue
            remark = str(item.get("remark") or "")
            nick = str(item.get("nick_name") or item.get("nickname") or "")
            alias = str(item.get("alias") or "")
            display = remark or nick or alias or username
            contacts[username] = Contact(
                username=username,
                display_name=display,
                remark=remark,
                nick_name=nick,
                is_group="@chatroom" in username,
            )
    return contacts


def resolve_contact(query: str, contacts: dict[str, Contact]) -> Contact | None:
    if query in contacts:
        return contacts[query]

    q = query.lower()
    exact = [c for c in contacts.values() if q == c.display_name.lower()]
    if exact:
        return exact[0]

    fuzzy = [
        c
        for c in contacts.values()
        if q in c.display_name.lower()
        or q in c.remark.lower()
        or q in c.nick_name.lower()
        or q in c.username.lower()
    ]
    return fuzzy[0] if fuzzy else None


def message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode()).hexdigest()


def _message_dbs(decrypted_dir: Path) -> list[Path]:
    message_dir = decrypted_dir / "message"
    if not message_dir.exists():
        return []
    return sorted(message_dir.glob("message_*.db"))


def _load_name2id(con: sqlite3.Connection) -> dict[int, str]:
    mapping: dict[int, str] = {}
    if not _table_exists(con, "Name2Id"):
        return mapping
    try:
        for row in con.execute("SELECT rowid, user_name FROM Name2Id"):
            if row["user_name"]:
                mapping[int(row["rowid"])] = str(row["user_name"])
    except sqlite3.Error:
        return {}
    return mapping


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row["name"] for row in con.execute(f"PRAGMA table_info([{table}])")}
    except sqlite3.Error:
        return set()


def _pick_column(columns: set[str], choices: tuple[str, ...]) -> str | None:
    for choice in choices:
        if choice in columns:
            return choice
    return None


def _decode_content(value, compression_flag: int | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    data = bytes(value)
    should_try_zstd = data.startswith(ZSTD_MAGIC) or compression_flag == 4
    if should_try_zstd and _ZSTD_DECODER:
        try:
            data = _ZSTD_DECODER.decompress(data, max_output_size=1_000_000)
        except Exception:
            pass
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def collect_messages(
    decrypted_dir: Path,
    username: str,
    my_wxid: str | None = None,
    *,
    include_content: bool = False,
) -> list[Message]:
    """收集指定联系人的全部消息。"""
    table = message_table(username)
    messages: list[Message] = []

    for db_path in _message_dbs(decrypted_dir):
        with _connect(db_path) as con:
            if not _table_exists(con, table):
                continue

            columns = _table_columns(con, table)
            type_col = _pick_column(columns, ("local_type", "type"))
            time_col = _pick_column(columns, ("create_time", "timestamp"))
            sender_col = _pick_column(columns, ("real_sender_id", "sender_id"))
            id_col = _pick_column(columns, ("local_id", "id")) or "rowid"
            content_col = _pick_column(columns, ("message_content", "content"))
            compress_col = _pick_column(columns, ("WCDB_CT_message_content",))

            if not type_col or not time_col:
                continue

            name2id = _load_name2id(con)
            my_sender_ids = set()
            contact_sender_ids = set()
            if my_wxid:
                for sid, uname in name2id.items():
                    if uname == my_wxid:
                        my_sender_ids.add(sid)
            for sid, uname in name2id.items():
                if uname == username:
                    contact_sender_ids.add(sid)

            select_cols = [f"{id_col} AS local_id", f"{type_col} AS local_type", f"{time_col} AS create_time"]
            if sender_col:
                select_cols.append(f"{sender_col} AS real_sender_id")
            if include_content and content_col:
                select_cols.append(f"{content_col} AS message_content")
                if compress_col:
                    select_cols.append(f"{compress_col} AS compression_flag")
            sql = f"SELECT {', '.join(select_cols)} FROM [{table}] ORDER BY {time_col}"

            for row in con.execute(sql):
                local_type = int(row["local_type"] or 0)
                create_time = int(row["create_time"] or 0)
                is_sender = False
                if sender_col:
                    sender_id = row["real_sender_id"]
                    if sender_id is not None:
                        sid = int(sender_id)
                        if my_sender_ids:
                            is_sender = sid in my_sender_ids
                        elif contact_sender_ids and "@chatroom" not in username:
                            is_sender = sid not in contact_sender_ids

                text = ""
                if include_content and content_col:
                    flag = row["compression_flag"] if compress_col else None
                    text = _decode_content(row["message_content"], flag).strip()

                messages.append(
                    Message(
                        local_id=int(row["local_id"] or 0),
                        local_type=local_type,
                        type_name=type_label(local_type),
                        create_time=create_time,
                        is_sender=is_sender,
                        text=text,
                    )
                )

    messages.sort(key=lambda m: m.create_time)
    return messages


def list_contacts_with_messages(decrypted_dir: Path, contacts: dict[str, Contact]) -> list[tuple[Contact, int]]:
    """列出有聊天记录的联系人及消息数。"""
    counts: dict[str, int] = {}

    for db_path in _message_dbs(decrypted_dir):
        with _connect(db_path) as con:
            tables = [
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                )
            ]
            for table in tables:
                target = table[4:]
                username = ""
                for uname in contacts:
                    if hashlib.md5(uname.encode()).hexdigest() == target:
                        username = uname
                        break
                if not username:
                    continue
                try:
                    count = con.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
                    counts[username] = counts.get(username, 0) + int(count)
                except sqlite3.Error:
                    continue

    result = [(contacts[u], c) for u, c in counts.items() if u in contacts]
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def detect_my_wxid(decrypted_dir: Path) -> str | None:
    """推断当前登录用户的 wxid。"""
    marker = decrypted_dir / ".my_wxid"
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip() or None

    # 从 .wechat_stats/keys.json 中的 _db_dir 路径解析账号目录名
    keys_file = decrypted_dir.parent / "keys.json"
    if keys_file.exists():
        import json

        try:
            data = json.loads(keys_file.read_text(encoding="utf-8"))
            db_dir = data.get("_db_dir", "")
            account_dir = Path(db_dir).parent.name
            if account_dir.startswith("wxid_"):
                wxid = account_dir.split("_d256")[0] if "_d256" in account_dir else account_dir.rsplit("_", 1)[0]
                if wxid.startswith("wxid_"):
                    marker.write_text(wxid, encoding="utf-8")
                    return wxid
        except (json.JSONDecodeError, OSError):
            pass

    # 从 message DB 的 Name2Id 中找最可能的自身 wxid（短 wxid 格式）
    for db_path in _message_dbs(decrypted_dir):
        with _connect(db_path) as con:
            if not _table_exists(con, "Name2Id"):
                continue
            try:
                for row in con.execute(
                    "SELECT user_name FROM Name2Id WHERE user_name LIKE 'wxid_%' AND length(user_name) < 25 LIMIT 5"
                ):
                    wxid = str(row["user_name"])
                    if wxid.count("_") <= 2:
                        marker.write_text(wxid, encoding="utf-8")
                        return wxid
            except sqlite3.Error:
                continue
    return None
