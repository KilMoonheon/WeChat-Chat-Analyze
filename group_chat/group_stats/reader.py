"""读取群聊消息及成员信息。"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from wechat_stats.reader import (
    Contact,
    _connect,
    _decode_content,
    _load_name2id,
    _message_dbs,
    _pick_column,
    _table_columns,
    _table_exists,
    load_contacts,
    message_table,
    resolve_contact,
)
from wechat_stats.types import type_label

WXID_PREFIX_RE = re.compile(r"^(wxid_[a-z0-9]+|[a-zA-Z0-9_-]+):\s*", re.IGNORECASE)

__all__ = [
    "Contact",
    "GroupMessage",
    "collect_group_messages",
    "list_groups",
    "load_contacts",
    "resolve_contact",
]


@dataclass
class GroupMessage:
    local_id: int
    sender_wxid: str
    sender_name: str
    local_type: int
    type_name: str
    create_time: int
    text: str


def list_groups(decrypted_dir: Path, contacts: dict[str, Contact]) -> list[tuple[Contact, int]]:
    counts: dict[str, int] = {}
    group_usernames = {u for u, c in contacts.items() if c.is_group}

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
                for uname in group_usernames:
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


def _display_name(wxid: str, contacts: dict[str, Contact]) -> str:
    if wxid in contacts:
        return contacts[wxid].display_name
    return wxid or "未知成员"


def _clean_group_text(raw: str, sender_wxid: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    text = WXID_PREFIX_RE.sub("", text, count=1)
    if text.startswith(f"{sender_wxid}:"):
        text = text.split(":", 1)[1].strip()
    if ":\n" in text[:40]:
        prefix, body = text.split(":\n", 1)
        if prefix.startswith("wxid_") or len(prefix) < 30:
            text = body.strip()
    return text.strip()


def collect_group_messages(
    decrypted_dir: Path,
    group_username: str,
    contacts: dict[str, Contact],
    *,
    include_content: bool = True,
) -> list[GroupMessage]:
    table = message_table(group_username)
    messages: list[GroupMessage] = []

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

            if not type_col or not time_col or not sender_col:
                continue

            name2id = _load_name2id(con)
            select_cols = [
                f"{id_col} AS local_id",
                f"{type_col} AS local_type",
                f"{time_col} AS create_time",
                f"{sender_col} AS real_sender_id",
            ]
            if include_content and content_col:
                select_cols.append(f"{content_col} AS message_content")
                if compress_col:
                    select_cols.append(f"{compress_col} AS compression_flag")

            sql = f"SELECT {', '.join(select_cols)} FROM [{table}] ORDER BY {time_col}"
            for row in con.execute(sql):
                sender_id = row["real_sender_id"]
                sender_wxid = name2id.get(int(sender_id or 0), "") if sender_id is not None else ""
                if not sender_wxid:
                    continue

                local_type = int(row["local_type"] or 0)
                text = ""
                if include_content and content_col:
                    flag = row["compression_flag"] if compress_col else None
                    raw = _decode_content(row["message_content"], flag)
                    text = _clean_group_text(raw, sender_wxid)

                messages.append(
                    GroupMessage(
                        local_id=int(row["local_id"] or 0),
                        sender_wxid=sender_wxid,
                        sender_name=_display_name(sender_wxid, contacts),
                        local_type=local_type,
                        type_name=type_label(local_type),
                        create_time=int(row["create_time"] or 0),
                        text=text,
                    )
                )

    messages.sort(key=lambda m: m.create_time)
    return messages
