"""群成员发言统计与内容偏好分析。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from group_chat.group_stats.reader import GroupMessage

from wechat_stats.personality import (
    PersonMessage,
    PersonProfile,
    analyze_person,
    render_member_personality_section,
)

WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
BRACKET_EMOJI_RE = re.compile(r"\[[^\[\]]{1,8}\]")
URL_RE = re.compile(r"https?://\S+|www\.\S+")

TYPE_ORDER = ["文字", "图片", "语音", "视频", "表情", "链接/文件", "通话", "位置", "名片", "系统消息", "撤回", "其他"]
HOUR_LABELS = list(range(24))
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclass
class MemberStats:
    wxid: str
    display_name: str
    total: int = 0
    share_pct: float = 0.0
    by_type: dict[str, int] = field(default_factory=dict)
    by_month: dict[str, int] = field(default_factory=dict)
    by_hour: dict[int, int] = field(default_factory=dict)
    by_weekday: dict[int, int] = field(default_factory=dict)
    first_active: datetime | None = None
    last_active: datetime | None = None
    text_count: int = 0
    avg_text_len: float = 0.0
    top_words: list[tuple[str, int]] = field(default_factory=list)
    top_emojis: list[tuple[str, int]] = field(default_factory=list)
    link_count: int = 0
    preference_summary: str = ""
    personality: PersonProfile | None = None

    def active_period_label(self) -> str:
        if not self.by_hour:
            return "未知"
        peak = max(self.by_hour.items(), key=lambda x: x[1])[0]
        if 6 <= peak < 12:
            return "上午型"
        if 12 <= peak < 18:
            return "下午型"
        if 18 <= peak < 23:
            return "晚间型"
        return "深夜型"

    def dominant_type(self) -> str:
        if not self.by_type:
            return "未知"
        ignore = {"系统消息", "撤回"}
        items = [(k, v) for k, v in self.by_type.items() if k not in ignore and v > 0]
        if not items:
            return "未知"
        return max(items, key=lambda x: x[1])[0]


def _build_preference_summary(stats: MemberStats) -> str:
    parts: list[str] = []
    if stats.total == 0:
        return "暂无发言数据"

    dom = stats.dominant_type()
    dom_pct = 100 * stats.by_type.get(dom, 0) / stats.total
    parts.append(f"主要使用{dom}（占 {dom_pct:.0f}%）")

    type_bits = []
    for name in ("文字", "图片", "语音", "视频", "表情", "链接/文件"):
        cnt = stats.by_type.get(name, 0)
        if cnt and name != dom:
            pct = 100 * cnt / stats.total
            if pct >= 8:
                type_bits.append(f"{name}{pct:.0f}%")
    if type_bits:
        parts.append("也会发" + "、".join(type_bits[:3]))

    parts.append(f"{stats.active_period_label()}（高峰约 {max(stats.by_hour, key=stats.by_hour.get):02d}:00）")

    if stats.top_emojis:
        emojis = "".join(e for e, _ in stats.top_emojis[:4])
        parts.append(f"常用表情{emojis}")

    if stats.link_count >= 3:
        parts.append(f"较常分享链接（{stats.link_count} 次）")

    if stats.avg_text_len >= 40:
        parts.append("文字偏长，倾向详细表达")
    elif stats.text_count >= 5 and stats.avg_text_len <= 12:
        parts.append("文字偏短，倾向简短互动")

    if stats.top_words:
        words = "、".join(w for w, _ in stats.top_words[:5])
        parts.append(f"高频词：{words}")

    return "；".join(parts)


def analyze_members(
    messages: list[GroupMessage],
    group_total: int | None = None,
) -> dict[str, MemberStats]:
    """按成员聚合统计。"""
    group_total = group_total or len(messages)
    buckets: dict[str, list[GroupMessage]] = defaultdict(list)
    for msg in messages:
        buckets[msg.sender_wxid].append(msg)

    result: dict[str, MemberStats] = {}
    for wxid, msgs in buckets.items():
        display = msgs[0].sender_name
        stats = MemberStats(
            wxid=wxid,
            display_name=display,
            total=len(msgs),
            share_pct=100 * len(msgs) / group_total if group_total else 0,
        )

        type_counter: Counter[str] = Counter()
        month_counter: Counter[str] = Counter()
        hour_counter: Counter[int] = Counter()
        weekday_counter: Counter[int] = Counter()
        word_counter: Counter[str] = Counter()
        emoji_counter: Counter[str] = Counter()
        text_lengths: list[int] = []

        for msg in msgs:
            type_counter[msg.type_name] += 1
            if msg.create_time <= 0:
                continue
            dt = datetime.fromtimestamp(msg.create_time)
            if stats.first_active is None or dt < stats.first_active:
                stats.first_active = dt
            if stats.last_active is None or dt > stats.last_active:
                stats.last_active = dt
            month_counter[dt.strftime("%Y-%m")] += 1
            hour_counter[dt.hour] += 1
            weekday_counter[dt.weekday()] += 1

            if msg.type_name == "文字" and msg.text:
                stats.text_count += 1
                text_lengths.append(len(msg.text))
                word_counter.update(w for w in WORD_RE.findall(msg.text) if len(w) <= 6)
                emoji_counter.update(BRACKET_EMOJI_RE.findall(msg.text))
                if URL_RE.search(msg.text):
                    stats.link_count += 1
            elif msg.type_name == "链接/文件":
                stats.link_count += 1

        stats.by_type = dict(type_counter)
        stats.by_month = dict(month_counter)
        stats.by_hour = dict(hour_counter)
        stats.by_weekday = dict(weekday_counter)
        stats.avg_text_len = sum(text_lengths) / len(text_lengths) if text_lengths else 0.0
        stats.top_words = word_counter.most_common(8)
        stats.top_emojis = emoji_counter.most_common(6)
        stats.preference_summary = _build_preference_summary(stats)
        person_msgs = [
            PersonMessage(type_name=m.type_name, create_time=m.create_time, text=m.text)
            for m in msgs
        ]
        stats.personality = analyze_person(display, person_msgs)
        result[wxid] = stats

    return result


def render_group_report(group_name: str, members: dict[str, MemberStats], total_messages: int) -> str:
    ranked = sorted(members.values(), key=lambda m: m.total, reverse=True)
    lines = [
        f"群聊: {group_name}",
        f"总消息数: {total_messages:,} 条",
        f"活跃成员: {len(ranked)} 人",
        "",
        f"{'排名':<4} {'成员':<16} {'发言数':>8} {'占比':>7} {'主要类型':<8} {'活跃时段':<6}",
        "-" * 62,
    ]
    for i, m in enumerate(ranked[:30], 1):
        lines.append(
            f"{i:<4} {m.display_name[:16]:<16} {m.total:>8,} {m.share_pct:>6.1f}% "
            f"{m.dominant_type():<8} {m.active_period_label():<6}"
        )

    lines.extend(["", "=" * 62, "成员内容偏好详情", "=" * 62, ""])
    for i, m in enumerate(ranked[:20], 1):
        lines.extend([
            f"【{i}】{m.display_name}（{m.total:,} 条，占 {m.share_pct:.1f}%）",
            f"  偏好: {m.preference_summary}",
            "",
        ])

    profiles = [m.personality for m in ranked if m.personality]
    if profiles:
        lines.append("")
        lines.append(render_member_personality_section(profiles, limit=20))

    return "\n".join(lines)
