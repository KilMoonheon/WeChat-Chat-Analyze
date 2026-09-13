"""群聊分析路径配置。"""

from __future__ import annotations

from pathlib import Path

from wechat_stats.config import DEFAULT_DECRYPTED_DIR, PROJECT_ROOT

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "group"


def ensure_output_dir() -> None:
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
