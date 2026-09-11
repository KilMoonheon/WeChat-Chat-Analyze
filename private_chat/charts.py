"""生成统计图表。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from private_chat.stats import ChatStats, WEEKDAY_NAMES
from wechat_stats.types import CHAT_TYPE_ORDER

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _safe_name(name: str) -> str:
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "contact"


def generate_charts(stats: ChatStats, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_name(stats.contact.display_name)
    saved: list[Path] = []

    saved.append(_chart_type_distribution(stats, output_dir / f"{prefix}_类型分布.png"))
    saved.append(_chart_monthly_frequency(stats, output_dir / f"{prefix}_月度频率.png"))
    saved.append(_chart_daily_recent(stats, output_dir / f"{prefix}_近期日频率.png"))
    saved.append(_chart_hourly_distribution(stats, output_dir / f"{prefix}_时段分布.png"))
    saved.append(_chart_weekday_distribution(stats, output_dir / f"{prefix}_星期分布.png"))

    if stats.sent_count or stats.received_count:
        saved.append(_chart_sent_received(stats, output_dir / f"{prefix}_收发比例.png"))

    report_path = output_dir / f"{prefix}_统计报告.txt"
    report_path.write_text(stats.summary_text(), encoding="utf-8")
    saved.append(report_path)

    return saved


def _chart_type_distribution(stats: ChatStats, path: Path) -> Path:
    labels = []
    values = []
    for name in CHAT_TYPE_ORDER:
        count = stats.by_type.get(name, 0)
        if count:
            labels.append(name)
            values.append(count)
    for name, count in sorted(stats.by_type.items()):
        if name not in CHAT_TYPE_ORDER and count:
            labels.append(name)
            values.append(count)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(f"与 {stats.contact.display_name} 的消息类型分布 (共 {stats.total:,} 条)", fontsize=14)

    colors = plt.cm.Set3(range(len(labels)))
    ax1.pie(values, labels=labels, autopct="%1.1f%%", colors=colors, startangle=90)
    ax1.set_title("占比")

    ax2.barh(labels, values, color=colors)
    ax2.set_xlabel("消息数")
    ax2.set_title("数量")
    for i, v in enumerate(values):
        ax2.text(v + max(values) * 0.01, i, f"{v:,}", va="center", fontsize=9)

    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_monthly_frequency(stats: ChatStats, path: Path) -> Path:
    if not stats.by_month:
        return path

    df = pd.DataFrame(
        sorted(stats.by_month.items()),
        columns=["month", "count"],
    )

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(df["month"], df["count"], color="#4C9AFF", alpha=0.85)
    ax.plot(df["month"], df["count"], color="#FF6B6B", marker="o", linewidth=2)
    ax.set_title(f"与 {stats.contact.display_name} 的月度聊天频率")
    ax.set_xlabel("月份")
    ax.set_ylabel("消息数")
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_daily_recent(stats: ChatStats, path: Path) -> Path:
    if not stats.by_day:
        return path

    items = sorted(stats.by_day.items())[-90:]
    df = pd.DataFrame(items, columns=["day", "count"])

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.fill_between(range(len(df)), df["count"], alpha=0.3, color="#4C9AFF")
    ax.plot(range(len(df)), df["count"], color="#4C9AFF", linewidth=1.5)
    ax.set_title(f"与 {stats.contact.display_name} 的近期日聊天频率 (最近 {len(df)} 天)")
    ax.set_xlabel("日期")
    ax.set_ylabel("消息数")
    step = max(1, len(df) // 10)
    ax.set_xticks(range(0, len(df), step))
    ax.set_xticklabels([df["day"].iloc[i] for i in range(0, len(df), step)], rotation=45)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_hourly_distribution(stats: ChatStats, path: Path) -> Path:
    hours = list(range(24))
    counts = [stats.by_hour.get(h, 0) for h in hours]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(hours, counts, color="#95E1D3", edgecolor="#38A3A5")
    ax.set_title(f"与 {stats.contact.display_name} 的聊天时段分布")
    ax.set_xlabel("小时 (0-23)")
    ax.set_ylabel("消息数")
    ax.set_xticks(hours)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_weekday_distribution(stats: ChatStats, path: Path) -> Path:
    counts = [stats.by_weekday.get(i, 0) for i in range(7)]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(WEEKDAY_NAMES, counts, color="#F38181", edgecolor="#AA4465")
    ax.set_title(f"与 {stats.contact.display_name} 的星期分布")
    ax.set_ylabel("消息数")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_sent_received(stats: ChatStats, path: Path) -> Path:
    labels = ["我发送", "对方/群友"]
    values = [stats.sent_count, stats.received_count]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.pie(
        values,
        labels=[f"{l}\n{v:,}条" for l, v in zip(labels, values)],
        autopct="%1.1f%%",
        colors=["#FFD93D", "#6BCB77"],
        startangle=90,
    )
    ax.set_title(f"与 {stats.contact.display_name} 的收发比例")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path
