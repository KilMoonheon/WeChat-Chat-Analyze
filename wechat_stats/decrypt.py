"""微信数据库解密封装。"""

from __future__ import annotations

from pathlib import Path

from wechat_stats.config import DEFAULT_DECRYPTED_DIR, DEFAULT_KEYS_FILE, ensure_work_dirs
from wechat_stats import wcdb


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

    account_name = db_path.parent.name
    if account_name.startswith("wxid_"):
        wxid = account_name.split("_d256")[0] if "_d256" in account_name else account_name.rsplit("_", 1)[0]
        (out_decrypted / ".my_wxid").write_text(wxid, encoding="utf-8")

    return out_decrypted
