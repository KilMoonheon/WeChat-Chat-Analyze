"""微信消息类型定义。"""

from __future__ import annotations

TYPE_LABELS: dict[int, str] = {
    1: "文字",
    3: "图片",
    34: "语音",
    42: "名片",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "链接/文件",
    50: "通话",
    10000: "系统消息",
    10002: "撤回",
}

CHAT_TYPE_ORDER = ["文字", "图片", "语音", "视频", "表情", "链接/文件", "通话", "位置", "名片", "系统消息", "撤回", "其他"]


def split_msg_type(local_type: int | None) -> tuple[int, int]:
    try:
        value = int(local_type or 0)
    except (TypeError, ValueError):
        return 0, 0
    if value > 0xFFFFFFFF:
        return value & 0xFFFFFFFF, value >> 32
    return value, 0


def type_label(local_type: int | None) -> str:
    base_type, _ = split_msg_type(local_type)
    return TYPE_LABELS.get(base_type, "其他")
