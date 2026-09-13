"""生成统计图表。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
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
    saved.append(_chart_frequency_heatmap(stats, output_dir / f"{prefix}_聊天频次热力图.png"))

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


def _chart_frequency_heatmap(stats: ChatStats, path: Path) -> Path:
    """全量聊天记录频次热力图：日历日频次 + 星期×小时分布。"""
    if not stats.by_day or not stats.first_message or not stats.last_message:
        return path

    start = stats.first_message.date()
    end = stats.last_message.date()
    span_days = (end - start).days + 1
    start_monday = start - timedelta(days=start.weekday())

    weeks: list[list[float]] = []
    week_starts: list = []
    current = start_monday
    while current <= end:
        week: list[float] = []
        for dow in range(7):
            day = current + timedelta(days=dow)
            key = day.strftime("%Y-%m-%d")
            if day < start or day > end:
                week.append(np.nan)
            else:
                week.append(float(stats.by_day.get(key, 0)))
        weeks.append(week)
        week_starts.append(current)
        current += timedelta(days=7)

    cal_arr = np.array(weeks, dtype=float).T  # 7 × num_weeks
    num_weeks = len(weeks)

    wh_arr = np.zeros((7, 24))
    for (wd, hr), cnt in stats.by_weekday_hour.items():
        wh_arr[wd, hr] = cnt

    fig_h = 7.5
    fig_w = min(52, max(16, num_weeks * 0.24 + 6))
    fig, (ax_cal, ax_wh) = plt.subplots(
        2, 1, figsize=(fig_w, fig_h), gridspec_kw={"height_ratios": [1.2, 1], "hspace": 0.35}
    )

    cmap_cal = plt.cm.YlOrRd.copy()
    cmap_cal.set_bad(color="#F0F0F0")
    im_cal = ax_cal.imshow(cal_arr, aspect="auto", cmap=cmap_cal, interpolation="nearest")
    ax_cal.set_yticks(range(7))
    ax_cal.set_yticklabels(WEEKDAY_NAMES)
    ax_cal.set_ylabel("星期")

    month_ticks: list[int] = []
    month_labels: list[str] = []
    seen_months: set[tuple[int, int]] = set()
    for i, ws in enumerate(week_starts):
        for day_offset in range(7):
            d = ws + timedelta(days=day_offset)
            if start <= d <= end:
                key = (d.year, d.month)
                if key not in seen_months:
                    seen_months.add(key)
                    month_ticks.append(i)
                    if d.year == start.year and d.year == end.year:
                        month_labels.append(f"{d.month}月")
                    else:
                        month_labels.append(f"{d.year}/{d.month}")
                break
    ax_cal.set_xticks(month_ticks)
    ax_cal.set_xticklabels(month_labels, fontsize=8)
    ax_cal.set_title(
        f"与 {stats.contact.display_name} 的聊天频次热力图（全量 {span_days} 天，{stats.total:,} 条消息）"
        f"\n{start} ~ {end}",
        fontsize=12,
    )
    fig.colorbar(im_cal, ax=ax_cal, label="日消息数", shrink=0.85, pad=0.02)

    im_wh = ax_wh.imshow(wh_arr, aspect="auto", cmap="YlOrRd", interpolation="nearest")
    ax_wh.set_yticks(range(7))
    ax_wh.set_yticklabels(WEEKDAY_NAMES)
    ax_wh.set_xticks(range(0, 24, 2))
    ax_wh.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
    ax_wh.set_xlabel("小时")
    ax_wh.set_ylabel("星期")
    ax_wh.set_title("星期 × 小时 发言分布（基于全部聊天记录汇总）")
    fig.colorbar(im_wh, ax=ax_wh, label="消息数", shrink=0.85, pad=0.02)

    fig.subplots_adjust(hspace=0.4)
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
