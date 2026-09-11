"""路径与配置。"""

from __future__ import annotations

import glob
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORK_DIR = PROJECT_ROOT / ".wechat_stats"
DEFAULT_DECRYPTED_DIR = DEFAULT_WORK_DIR / "decrypted"
DEFAULT_KEYS_FILE = DEFAULT_WORK_DIR / "keys.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"


def auto_detect_db_dir() -> Path | None:
    """自动检测微信 4.x 数据库目录。"""
    appdata = os.environ.get("APPDATA", "")
    config_dir = os.path.join(appdata, "Tencent", "xwechat", "config")
    data_roots: list[str] = []

    if os.path.isdir(config_dir):
        for ini_file in glob.glob(os.path.join(config_dir, "*.ini")):
            for enc in ("utf-8", "gbk"):
                try:
                    with open(ini_file, "r", encoding=enc) as f:
                        content = f.read(1024).strip()
                    if content and os.path.isdir(content):
                        data_roots.append(content)
                    break
                except (UnicodeDecodeError, OSError):
                    continue

    candidates: list[str] = []
    default_docs = os.path.join(os.path.expanduser("~"), "Documents", "xwechat_files")
    if os.path.isdir(default_docs):
        data_roots.append(os.path.dirname(default_docs))

    for root in data_roots:
        pattern = os.path.join(root, "xwechat_files", "*", "db_storage")
        for match in glob.glob(pattern):
            if os.path.isdir(match) and match not in candidates:
                candidates.append(match)

    if not candidates:
        legacy = os.path.join(os.path.expanduser("~"), "Documents", "xwechat_files", "*", "db_storage")
        for match in glob.glob(legacy):
            if os.path.isdir(match):
                candidates.append(match)

    return Path(candidates[0]) if candidates else None


def ensure_work_dirs() -> None:
    DEFAULT_WORK_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DECRYPTED_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
