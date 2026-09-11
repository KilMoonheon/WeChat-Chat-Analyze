#!/usr/bin/env python3
"""私聊统计分析入口。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from private_chat.cli import main

if __name__ == "__main__":
    sys.exit(main())
