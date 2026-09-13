"""聊天统计分析。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from wechat_stats.reader import Contact, Message
from wechat_stats.types import CHAT_TYPE_ORDER


@dataclass
class ChatStats:
    contact: Contact
    total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_month: dict[str, int] = field(default_factory=dict)
    by_day: dict[str, int] = field(default_factory=dict)
    by_hour: dict[int, int] = field(default_factory=dict)
    by_weekday: dict[int, int] = field(default_factory=dict)
    by_weekday_hour: dict[tuple[int, int], int] = field(default_factory=dict)
    sent_count: int = 0
    received_count: int = 0
    first_message: datetime | None = None
    last_message: datetime | None = None

    def summary_text(self) -> str:
        lines = [
            f"联系人: {self.contact.display_name}",
            f"微信 ID: {self.contact.username}",
            f"{'群聊' if self.contact.is_group else '私聊'}",
            "",
            f"总消息数: {self.total:,} 条",
        ]

        if self.sent_count or self.received_count:
            lines.append(f"  我发送: {self.sent_count:,} 条")
            lines.append(f"  对方/群友: {self.received_count:,} 条")

        if self.first_message and self.last_message:
            lines.extend(
                [
                    "",
                    f"首条消息: {self.first_message.strftime('%Y-%m-%d %H:%M')}",
                    f"末条消息: {self.last_message.strftime('%Y-%m-%d %H:%M')}",
                    f"跨度: {(self.last_message - self.first_message).days} 天",
                ]
            )

        lines.extend(["", "按类型统计:"])
        for name in CHAT_TYPE_ORDER:
            count = self.by_type.get(name, 0)
            if count:
                pct = 100 * count / self.total if self.total else 0
                lines.append(f"  {name}: {count:,} 条 ({pct:.1f}%)")

        for name, count in sorted(self.by_type.items()):
            if name not in CHAT_TYPE_ORDER and count:
                pct = 100 * count / self.total if self.total else 0
                lines.append(f"  {name}: {count:,} 条 ({pct:.1f}%)")

        if self.by_month:
            lines.extend(["", "最活跃的月份 (Top 5):"])
            top_months = sorted(self.by_month.items(), key=lambda x: x[1], reverse=True)[:5]
            for month, count in top_months:
                lines.append(f"  {month}: {count:,} 条")

        return "\n".join(lines)


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def compute_stats(contact: Contact, messages: list[Message]) -> ChatStats:
    stats = ChatStats(contact=contact, total=len(messages))
    type_counter: Counter[str] = Counter()
    month_counter: Counter[str] = Counter()
    day_counter: Counter[str] = Counter()
    hour_counter: Counter[int] = Counter()
    weekday_counter: Counter[int] = Counter()
    weekday_hour_counter: Counter[tuple[int, int]] = Counter()

    for msg in messages:
        type_counter[msg.type_name] += 1
        if msg.is_sender:
            stats.sent_count += 1
        else:
            stats.received_count += 1

        if msg.create_time <= 0:
            continue

        dt = datetime.fromtimestamp(msg.create_time)
        if stats.first_message is None or dt < stats.first_message:
            stats.first_message = dt
        if stats.last_message is None or dt > stats.last_message:
            stats.last_message = dt

        month_counter[dt.strftime("%Y-%m")] += 1
        day_counter[dt.strftime("%Y-%m-%d")] += 1
        hour_counter[dt.hour] += 1
        weekday_counter[dt.weekday()] += 1
        weekday_hour_counter[(dt.weekday(), dt.hour)] += 1

    stats.by_type = dict(type_counter)
    stats.by_month = dict(month_counter)
    stats.by_day = dict(day_counter)
    stats.by_hour = dict(hour_counter)
    stats.by_weekday = dict(weekday_counter)
    stats.by_weekday_hour = dict(weekday_hour_counter)
    return stats
