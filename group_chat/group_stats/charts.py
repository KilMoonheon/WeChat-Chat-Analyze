"""群聊成员分析图表。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from group_chat.group_stats.analyze import (
    GroupTimelineStats,
    MemberStats,
    TYPE_ORDER,
    WEEKDAY_LABELS,
)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _safe_name(name: str) -> str:
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "group"


def generate_group_charts(
    group_name: str,
    members: dict[str, MemberStats],
    total_messages: int,
    output_dir: Path,
    *,
    timeline: GroupTimelineStats | None = None,
    top_n: int = 15,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_name(group_name)
    ranked = sorted(members.values(), key=lambda m: m.total, reverse=True)
    top = ranked[:top_n]
    saved: list[Path] = []

    saved.append(_chart_member_counts(group_name, top, total_messages, output_dir / f"{prefix}_成员发言排行.png"))
    saved.append(_chart_member_share_pie(group_name, top, output_dir / f"{prefix}_发言占比.png"))
    saved.append(_chart_monthly_trend(group_name, top[:8], output_dir / f"{prefix}_月度发言趋势.png"))
    saved.append(_chart_hour_heatmap(group_name, top[:10], output_dir / f"{prefix}_成员时段热力图.png"))
    saved.append(_chart_type_stack(group_name, top[:10], output_dir / f"{prefix}_成员内容类型.png"))
    saved.append(_chart_weekday_distribution(group_name, ranked, output_dir / f"{prefix}_星期分布.png"))
    if timeline:
        saved.append(
            _chart_frequency_heatmap(
                group_name, timeline, output_dir / f"{prefix}_聊天频次热力图.png"
            )
        )
    return saved


def _chart_member_counts(group_name: str, members: list[MemberStats], total: int, path: Path) -> Path:
    names = [m.display_name for m in members][::-1]
    counts = [m.total for m in members][::-1]

    fig, ax = plt.subplots(figsize=(12, max(6, len(names) * 0.35)))
    colors = plt.cm.Blues(np.linspace(0.45, 0.9, len(names)))
    ax.barh(names, counts, color=colors)
    ax.set_title(f"{group_name} — 成员发言条数排行（共 {total:,} 条）")
    ax.set_xlabel("发言数")
    for i, v in enumerate(counts):
        ax.text(v + max(counts) * 0.01, i, f"{v:,}", va="center", fontsize=9)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_member_share_pie(group_name: str, members: list[MemberStats], path: Path) -> Path:
    labels = [m.display_name for m in members[:10]]
    values = [m.total for m in members[:10]]
    other = sum(m.total for m in members[10:]) if len(members) > 10 else 0
    if other:
        labels.append("其他")
        values.append(other)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=140, counterclock=False)
    ax.set_title(f"{group_name} — Top 成员发言占比")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_monthly_trend(group_name: str, members: list[MemberStats], path: Path) -> Path:
    all_months = sorted({m for mem in members for m in mem.by_month})
    if not all_months:
        return path

    fig, ax = plt.subplots(figsize=(14, 6))
    for mem in members:
        ys = [mem.by_month.get(m, 0) for m in all_months]
        ax.plot(all_months, ys, marker="o", linewidth=1.5, label=mem.display_name)
    ax.set_title(f"{group_name} — 活跃成员月度发言频率")
    ax.set_xlabel("月份")
    ax.set_ylabel("发言数")
    ax.legend(fontsize=8, ncol=2)
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_hour_heatmap(group_name: str, members: list[MemberStats], path: Path) -> Path:
    if not members:
        return path
    data = []
    labels = []
    for mem in members:
        labels.append(mem.display_name[:12])
        data.append([mem.by_hour.get(h, 0) for h in range(24)])
    arr = np.array(data)

    fig, ax = plt.subplots(figsize=(14, max(4, len(members) * 0.45)))
    im = ax.imshow(arr, aspect="auto", cmap="YlOrRd")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
    ax.set_xlabel("小时")
    ax.set_title(f"{group_name} — 成员发言时段分布")
    fig.colorbar(im, ax=ax, label="发言数")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_type_stack(group_name: str, members: list[MemberStats], path: Path) -> Path:
    names = [m.display_name for m in members]
    types_present = []
    for t in TYPE_ORDER:
        if any(m.by_type.get(t, 0) for m in members):
            types_present.append(t)

    fig, ax = plt.subplots(figsize=(14, max(5, len(names) * 0.4)))
    bottom = np.zeros(len(names))
    colors = plt.cm.Set3(np.linspace(0, 1, len(types_present)))
    x = np.arange(len(names))

    for i, tname in enumerate(types_present):
        vals = np.array([m.by_type.get(tname, 0) for m in members])
        ax.bar(x, vals, bottom=bottom, label=tname, color=colors[i])
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=35, ha="right")
    ax.set_ylabel("发言数")
    ax.set_title(f"{group_name} — 成员内容类型构成")
    ax.legend(fontsize=8, ncol=3, loc="upper right")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_frequency_heatmap(
    group_name: str, timeline: GroupTimelineStats, path: Path
) -> Path:
    """全量群聊记录频次热力图：日历日频次 + 星期×小时分布。"""
    if not timeline.by_day or not timeline.first_active or not timeline.last_active:
        return path

    start = timeline.first_active.date()
    end = timeline.last_active.date()
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
                week.append(float(timeline.by_day.get(key, 0)))
        weeks.append(week)
        week_starts.append(current)
        current += timedelta(days=7)

    cal_arr = np.array(weeks, dtype=float).T
    num_weeks = len(weeks)

    wh_arr = np.zeros((7, 24))
    for (wd, hr), cnt in timeline.by_weekday_hour.items():
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
    ax_cal.set_yticklabels(WEEKDAY_LABELS)
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
        f"{group_name} 群聊频次热力图（全量 {span_days} 天，{timeline.total:,} 条消息）"
        f"\n{start} ~ {end}",
        fontsize=12,
    )
    fig.colorbar(im_cal, ax=ax_cal, label="日消息数", shrink=0.85, pad=0.02)

    im_wh = ax_wh.imshow(wh_arr, aspect="auto", cmap="YlOrRd", interpolation="nearest")
    ax_wh.set_yticks(range(7))
    ax_wh.set_yticklabels(WEEKDAY_LABELS)
    ax_wh.set_xticks(range(0, 24, 2))
    ax_wh.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
    ax_wh.set_xlabel("小时")
    ax_wh.set_ylabel("星期")
    ax_wh.set_title("星期 × 小时 发言分布（基于全部群聊记录汇总）")
    fig.colorbar(im_wh, ax=ax_wh, label="消息数", shrink=0.85, pad=0.02)

    fig.subplots_adjust(hspace=0.4)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _chart_weekday_distribution(group_name: str, members: list[MemberStats], path: Path) -> Path:
    totals = [sum(m.by_weekday.get(i, 0) for m in members) for i in range(7)]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(WEEKDAY_LABELS, totals, color="#6BCB77", edgecolor="#40916C")
    ax.set_title(f"{group_name} — 全群星期发言分布")
    ax.set_ylabel("发言数")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path
