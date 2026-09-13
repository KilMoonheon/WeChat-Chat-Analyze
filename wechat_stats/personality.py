"""基于聊天记录的性格、语言特点与关注话题分析（启发式，非临床诊断）。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,6}")
BRACKET_EMOJI_RE = re.compile(r"\[[^\[\]]{1,8}\]")
URL_RE = re.compile(r"https?://\S+|www\.\S+")
QUESTION_RE = re.compile(r"[?？]|吗[?？]?|呢[?？]?|么[?？]?|是不是|有没有|能不能|可不可以")

CONCERN_THEMES: dict[str, list[str]] = {
    "工作与发展": ["工作", "实习", "面试", "招聘", "简历", "加班", "项目", "公司", "职场", "offer", "工资", "薪资", "岗位", "入职", "离职"],
    "学习与考试": ["学习", "考试", "作业", "论文", "课程", "复习", "毕业", "学校", "导师", "研究", "实验", "答辩", "考研"],
    "情感与关系": ["喜欢", "爱你", "想你", "抱抱", "开心", "难过", "生气", "在一起", "宝贝", "亲爱的", "想念", "约会"],
    "社交与活动": ["聚会", "团建", "活动", "报名", "会议", "摄影", "拍摄", "打卡", "志愿者", "宣讲", "招募"],
    "日常生活": ["吃饭", "睡觉", "天气", "快递", "外卖", "旅游", "回家", "周末", "放假", "逛街"],
    "健康与运动": ["健身", "运动", "跑步", "健康", "医院", "生病", "累", "休息", "锻炼"],
    "技术兴趣": ["代码", "编程", "python", "开发", "bug", "技术", "算法", "程序", "软件", "电脑"],
    "财务消费": ["钱", "价格", "优惠", "报销", "转账", "红包", "付款", "买", "消费"],
}


@dataclass
class PersonMessage:
    type_name: str
    create_time: int
    text: str = ""


@dataclass
class PersonProfile:
    label: str
    message_count: int = 0
    language_style: str = ""
    personality_traits: list[str] = field(default_factory=list)
    top_concerns: list[tuple[str, int]] = field(default_factory=list)
    concern_summary: str = ""
    top_words: list[tuple[str, int]] = field(default_factory=list)
    top_emojis: list[tuple[str, int]] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"▸ {self.label}",
            f"  消息数: {self.message_count:,} 条",
            "",
            "  【语言特点】",
            f"  {self.language_style}",
            "",
            "  【性格倾向】（基于聊天风格推断，仅供参考）",
        ]
        if self.personality_traits:
            for t in self.personality_traits:
                lines.append(f"  · {t}")
        elif self.message_count > 0:
            lines.append("  · 以非文字消息为主，性格推断有限")
        else:
            lines.append("  · 暂无足够消息")

        lines.extend(["", "  【最关心的事情】", f"  {self.concern_summary}"])
        if self.top_concerns:
            themes = "、".join(f"{name}({cnt})" for name, cnt in self.top_concerns[:4])
            lines.append(f"  话题分布: {themes}")
        if self.top_words:
            words = "、".join(w for w, _ in self.top_words[:6])
            lines.append(f"  高频词: {words}")
        if self.top_emojis:
            emojis = "".join(e for e, _ in self.top_emojis[:5])
            lines.append(f"  常用表情: {emojis}")
        return "\n".join(lines)


def _active_period(by_hour: Counter[int]) -> tuple[str, int]:
    if not by_hour:
        return "未知", 12
    peak = max(by_hour.items(), key=lambda x: x[1])[0]
    if 6 <= peak < 12:
        return "上午型", peak
    if 12 <= peak < 18:
        return "下午型", peak
    if 18 <= peak < 23:
        return "晚间型", peak
    return "深夜型", peak


def analyze_person(label: str, messages: list[PersonMessage]) -> PersonProfile:
    profile = PersonProfile(label=label, message_count=len(messages))
    if not messages:
        profile.language_style = "暂无足够消息"
        profile.concern_summary = "暂无数据"
        return profile

    type_counter: Counter[str] = Counter()
    hour_counter: Counter[int] = Counter()
    word_counter: Counter[str] = Counter()
    emoji_counter: Counter[str] = Counter()
    theme_counter: Counter[str] = Counter()

    text_lengths: list[int] = []
    question_count = 0
    exclaim_count = 0
    laugh_count = 0
    text_count = 0
    link_count = 0

    for msg in messages:
        type_counter[msg.type_name] += 1
        if msg.create_time > 0:
            hour_counter[datetime.fromtimestamp(msg.create_time).hour] += 1

        if msg.type_name == "链接/文件":
            link_count += 1

        if msg.type_name == "文字" and msg.text.strip():
            text = msg.text.strip()
            text_count += 1
            text_lengths.append(len(text))
            words = [w for w in WORD_RE.findall(text) if len(w) >= 2]
            word_counter.update(words)
            emoji_counter.update(BRACKET_EMOJI_RE.findall(text))
            if QUESTION_RE.search(text):
                question_count += 1
            if "!" in text or "！" in text:
                exclaim_count += 1
            if re.search(r"[哈呵嘿]{2,}|233|xs|笑死", text):
                laugh_count += 1
            if URL_RE.search(text):
                link_count += 1
            for theme, keywords in CONCERN_THEMES.items():
                if any(kw in text for kw in keywords):
                    theme_counter[theme] += 1

    total = len(messages)
    avg_len = sum(text_lengths) / len(text_lengths) if text_lengths else 0.0
    emoji_per_msg = sum(emoji_counter.values()) / total
    question_rate = question_count / text_count if text_count else 0
    exclaim_rate = exclaim_count / text_count if text_count else 0
    laugh_rate = laugh_count / text_count if text_count else 0
    text_pct = 100 * type_counter.get("文字", 0) / total
    voice_pct = 100 * type_counter.get("语音", 0) / total
    image_pct = 100 * type_counter.get("图片", 0) / total
    emoji_type_pct = 100 * type_counter.get("表情", 0) / total
    period, peak_hour = _active_period(hour_counter)

    # --- 语言特点 ---
    style_parts: list[str] = []
    if text_count == 0:
        style_parts.append("较少使用文字，更依赖语音/图片/表情交流")
    elif avg_len >= 35:
        style_parts.append("表达详尽，单条消息平均较长")
    elif avg_len <= 10:
        style_parts.append("表达简洁，倾向短句快速回复")
    else:
        style_parts.append("表达长度适中，兼顾信息与效率")

    if emoji_per_msg >= 0.5 or emoji_type_pct >= 15:
        style_parts.append("表情使用频繁，语气偏活泼")
    elif emoji_per_msg < 0.1 and emoji_type_pct < 5:
        style_parts.append("表情使用较少，语气偏克制")

    if question_rate >= 0.25:
        style_parts.append("常提问、确认细节，互动性强")
    if exclaim_rate >= 0.2 or laugh_rate >= 0.15:
        style_parts.append("感叹与幽默表达较多，情绪外显")
    if voice_pct >= 20:
        style_parts.append(f"偏好语音（占 {voice_pct:.0f}%）")
    if image_pct >= 20:
        style_parts.append(f"常发图片（占 {image_pct:.0f}%）")
    if link_count >= 3:
        style_parts.append(f"习惯分享链接/文件（{link_count} 次）")

    style_parts.append(f"活跃时段为{period}，高峰约 {peak_hour:02d}:00")
    profile.language_style = "；".join(style_parts)

    # --- 性格倾向 ---
    traits: list[str] = []
    if avg_len >= 30 and text_pct >= 40:
        traits.append("表达型：愿意展开说明，重视把事讲清楚")
    elif avg_len <= 12 and text_count >= 5:
        traits.append("简洁型：点到为止，聊天节奏快")

    if emoji_per_msg >= 0.4 or laugh_rate >= 0.12:
        traits.append("外向亲和：善用表情和语气词，氛围轻松")
    elif text_count >= 10 and emoji_per_msg < 0.08 and exclaim_rate < 0.1:
        traits.append("内敛克制：文字为主，情绪表达相对含蓄")

    if question_rate >= 0.2:
        traits.append("好奇互动：爱提问、爱确认，关注对方反馈")
    if link_count >= max(3, total * 0.08):
        traits.append("分享型：常转发链接/文件，乐于传递信息")

    if voice_pct >= 25:
        traits.append("语音偏好：更习惯用声音交流")
    if image_pct >= 25:
        traits.append("视觉偏好：倾向用图片表达")

    if peak_hour >= 22 or peak_hour <= 2:
        traits.append("夜猫倾向：深夜仍活跃")
    elif 7 <= peak_hour <= 9:
        traits.append("早起倾向：上午时段最活跃")

    if total >= 50 and text_pct >= 60:
        traits.append("文字主导：以打字为主要沟通方式")

    profile.personality_traits = traits[:6]

    # --- 关注话题 ---
    profile.top_words = word_counter.most_common(8)
    profile.top_emojis = emoji_counter.most_common(6)
    profile.top_concerns = theme_counter.most_common(5)

    if theme_counter:
        top_theme, top_cnt = theme_counter.most_common(1)[0]
        others = [f"{n}({c}次)" for n, c in theme_counter.most_common(4)[1:]]
        base = f"最关注「{top_theme}」相关话题（约 {top_cnt} 条消息涉及）"
        if others:
            base += "，其次涉及" + "、".join(others)
        profile.concern_summary = base
    elif profile.top_words:
        words = "、".join(w for w, _ in profile.top_words[:5])
        profile.concern_summary = f"未匹配到明确主题分类，高频讨论: {words}"
    else:
        profile.concern_summary = "文字消息较少，主要关注方向需结合语音/图片内容判断"

    return profile


def render_dual_report(me: PersonProfile, other: PersonProfile, title: str = "") -> str:
    header = ["=" * 50, "性格 · 语言 · 关注话题分析", "=" * 50, ""]
    if title:
        header.insert(0, title)
        header.insert(1, "")
    parts = header + [me.render(), "", "-" * 50, "", other.render(), ""]
    parts.append("※ 以上基于聊天文本与行为模式的启发式推断，仅供娱乐参考，不代表心理测评结果。")
    return "\n".join(parts)


def render_member_personality_section(profiles: list[PersonProfile], limit: int = 20) -> str:
    lines = ["=" * 62, "成员性格 · 语言 · 关注话题分析", "=" * 62, ""]
    for i, p in enumerate(profiles[:limit], 1):
        lines.append(f"{'─' * 40}")
        lines.append(p.render())
        lines.append("")
    lines.append("※ 以上基于聊天文本与行为模式的启发式推断，仅供娱乐参考。")
    return "\n".join(lines)
