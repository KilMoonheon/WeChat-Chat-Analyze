"""微信数据库解密封装。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from wechat_stats.config import DEFAULT_DECRYPTED_DIR, DEFAULT_KEYS_FILE, auto_detect_db_dir, ensure_work_dirs
from wechat_stats import wcdb


def _latest_db_mtime(root: Path) -> float:
    latest = 0.0
    if not root.is_dir():
        return latest
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if not fname.endswith(".db") or fname.endswith(("-wal", "-shm")):
                continue
            try:
                latest = max(latest, os.path.getmtime(os.path.join(dirpath, fname)))
            except OSError:
                pass
    return latest


def _sync_meta_path(decrypted_dir: Path) -> Path:
    return decrypted_dir / ".sync_meta.json"


def _write_sync_meta(db_dir: Path, decrypted_dir: Path) -> None:
    meta = {
        "source_mtime": _latest_db_mtime(db_dir),
        "synced_at": time.time(),
    }
    _sync_meta_path(decrypted_dir).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_data_stale(db_dir: Path, decrypted_dir: Path) -> bool:
    """加密源库是否比上次同步时更新。"""
    if not (decrypted_dir / "contact" / "contact.db").exists():
        return True
    src_mtime = _latest_db_mtime(db_dir)
    if src_mtime <= 0:
        return False

    meta_path = _sync_meta_path(decrypted_dir)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            last_src = float(meta.get("source_mtime", 0))
            return src_mtime > last_src + 1
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    dec_mtime = _latest_db_mtime(decrypted_dir)
    return src_mtime > dec_mtime + 1


def ensure_fresh_data(
    db_dir: Path | None = None,
    decrypted_dir: Path | None = None,
    *,
    force: bool = False,
) -> Path:
    """分析前自动同步：源库有更新则重新解密。"""
    db_path = Path(db_dir) if db_dir else auto_detect_db_dir()
    if not db_path:
        raise RuntimeError(
            "未能自动检测微信数据库目录。\n"
            "请确认微信 PC 版已登录，或使用 --db-dir 手动指定 db_storage 路径。"
        )

    out_decrypted = Path(decrypted_dir or DEFAULT_DECRYPTED_DIR)
    if force or is_data_stale(db_path, out_decrypted):
        if force:
            print("[*] 正在强制同步微信数据库...")
        else:
            src_ts = _latest_db_mtime(db_path)
            meta_path = _sync_meta_path(out_decrypted)
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    dec_ts = float(meta.get("synced_at", 0))
                except (json.JSONDecodeError, TypeError, ValueError):
                    dec_ts = _latest_db_mtime(out_decrypted)
            else:
                dec_ts = _latest_db_mtime(out_decrypted)
            src_label = datetime.fromtimestamp(src_ts).strftime("%Y-%m-%d %H:%M") if src_ts else "未知"
            dec_label = datetime.fromtimestamp(dec_ts).strftime("%Y-%m-%d %H:%M") if dec_ts else "无"
            print(f"[*] 检测到微信数据库有更新（源库 {src_label} > 上次同步 {dec_label}），正在自动同步...")
        return prepare_data(db_dir=db_path, decrypted_dir=out_decrypted)

    meta_path = _sync_meta_path(out_decrypted)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            dec_ts = float(meta.get("synced_at", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            dec_ts = _latest_db_mtime(out_decrypted)
    else:
        dec_ts = _latest_db_mtime(out_decrypted)
    label = datetime.fromtimestamp(dec_ts).strftime("%Y-%m-%d %H:%M") if dec_ts else "未知"
    print(f"[*] 本地数据已是最新（上次同步 {label}）")
    return out_decrypted


def prepare_data(
    db_dir: Path | None = None,
    decrypted_dir: Path | None = None,
    keys_file: Path | None = None,
) -> Path:
    """提取密钥并解密微信数据库。需要微信 PC 版正在运行。"""
    ensure_work_dirs()

    db_path = db_dir or wcdb.auto_detect_db_dir()
    if not db_path:
        raise RuntimeError(
            "未能自动检测微信数据库目录。\n"
            "请确认微信 PC 版已登录，或使用 --db-dir 手动指定 db_storage 路径。"
        )

    db_path = Path(db_path)
    out_decrypted = decrypted_dir or DEFAULT_DECRYPTED_DIR
    out_keys = keys_file or DEFAULT_KEYS_FILE

    print(f"[*] 微信数据库: {db_path}")
    print("[*] 正在从微信进程内存提取密钥（请保持微信运行）...")

    if not out_keys.exists():
        wcdb.scan_memory_keys(str(db_path), str(out_keys))

    print(f"[*] 正在解密到: {out_decrypted}")
    result = wcdb.decrypt_all(str(db_path), str(out_decrypted), str(out_keys))
    if result.get("success", 0) == 0:
        raise RuntimeError("数据库解密失败，请检查密钥是否正确")

    print(f"[+] 解密完成: {result['success']} 成功, {result['failed']} 失败")

    _write_sync_meta(db_path, out_decrypted)

    account_name = db_path.parent.name
    if account_name.startswith("wxid_"):
        wxid = account_name.split("_d256")[0] if "_d256" in account_name else account_name.rsplit("_", 1)[0]
        (out_decrypted / ".my_wxid").write_text(wxid, encoding="utf-8")

    return out_decrypted
