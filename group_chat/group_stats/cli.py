"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from group_chat.group_stats.analyze import (
    analyze_group_timeline,
    analyze_members,
    render_group_report,
)
from group_chat.group_stats.charts import generate_group_charts
from group_chat.group_stats.config import DEFAULT_OUTPUT_DIR, ensure_output_dir
from group_chat.group_stats.reader import collect_group_messages, list_groups
from wechat_stats.config import DEFAULT_DECRYPTED_DIR
from wechat_stats.decrypt import ensure_fresh_data, prepare_data
from wechat_stats.reader import load_contacts, resolve_contact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信群聊成员发言分析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_groups = sub.add_parser("groups", help="列出有聊天记录的群聊")
    p_groups.add_argument("--decrypted-dir", type=Path, default=DEFAULT_DECRYPTED_DIR)
    p_groups.add_argument("--db-dir", type=Path, help="微信 db_storage 目录")
    p_groups.add_argument("--search", type=str, help="按群名搜索")
    p_groups.add_argument("--no-sync", action="store_true", help="跳过自动同步，直接使用本地缓存")

    p_analyze = sub.add_parser("analyze", help="分析指定群聊的成员发言情况")
    p_analyze.add_argument("group", type=str, help="群名称关键词")
    p_analyze.add_argument("--decrypted-dir", type=Path, default=DEFAULT_DECRYPTED_DIR)
    p_analyze.add_argument("--db-dir", type=Path, help="微信 db_storage 目录")
    p_analyze.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    p_analyze.add_argument("--top", type=int, default=15, help="图表中展示的 Top 成员数")
    p_analyze.add_argument("--json", action="store_true", help="额外导出 JSON 数据")
    p_analyze.add_argument("--no-sync", action="store_true", help="跳过自动同步，直接使用本地缓存")

    p_prepare = sub.add_parser("prepare", help="提取密钥并解密微信数据库（需微信运行）")
    return parser


def _sync_or_fail(args: argparse.Namespace) -> Path | None:
    decrypted_dir = Path(args.decrypted_dir)
    if getattr(args, "no_sync", False):
        if not (decrypted_dir / "contact" / "contact.db").exists():
            print("未找到解密数据库。请先运行: python private_chat/main.py prepare")
            print(f"期望路径: {decrypted_dir}")
            return None
        return decrypted_dir
    try:
        return ensure_fresh_data(db_dir=getattr(args, "db_dir", None), decrypted_dir=decrypted_dir)
    except RuntimeError as exc:
        print(exc)
        return None


def cmd_groups(args: argparse.Namespace) -> int:
    decrypted_dir = _sync_or_fail(args)
    if decrypted_dir is None:
        return 1

    contacts = load_contacts(decrypted_dir)
    items = list_groups(decrypted_dir, contacts)
    if args.search:
        q = args.search.lower()
        items = [(c, n) for c, n in items if q in c.display_name.lower()]

    print(f"{'群名称':<28} {'消息数':>10}")
    print("-" * 42)
    for contact, count in items[:100]:
        print(f"{contact.display_name[:28]:<28} {count:>10,}")
    print(f"\n共 {len(items)} 个群聊")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    decrypted_dir = _sync_or_fail(args)
    if decrypted_dir is None:
        return 1

    contacts = load_contacts(decrypted_dir)
    group = resolve_contact(args.group, contacts)
    if not group or not group.is_group:
        print(f"未找到群聊: {args.group}")
        print("提示: python group_chat/main.py groups --search <关键词>")
        return 1

    print(f"[*] 正在分析群聊: {group.display_name}")
    print("[*] 读取消息中（大群可能需要几十秒）...")
    messages = collect_group_messages(decrypted_dir, group.username, contacts)
    if not messages:
        print("该群没有可分析的消息")
        return 1

    members = analyze_members(messages)
    timeline = analyze_group_timeline(messages)
    report = render_group_report(group.display_name, members, len(messages))
    print()
    print(report)

    out_dir = Path(args.output) / group.display_name.replace("/", "_")
    ensure_output_dir()
    report_path = out_dir / f"{group.display_name.replace('/', '_')}_成员分析报告.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    charts = generate_group_charts(
        group.display_name,
        members,
        len(messages),
        out_dir,
        timeline=timeline,
        top_n=args.top,
    )

    personality_path = out_dir / f"{group.display_name.replace('/', '_')}_性格与关注分析.txt"
    from wechat_stats.personality import render_member_personality_section

    profiles = [m.personality for m in sorted(members.values(), key=lambda x: x.total, reverse=True) if m.personality]
    personality_path.write_text(
        render_member_personality_section(profiles, limit=len(profiles)),
        encoding="utf-8",
    )
    charts.append(personality_path)

    if args.json:
        json_path = out_dir / "members.json"
        payload = {
            m.wxid: {
                "display_name": m.display_name,
                "total": m.total,
                "share_pct": round(m.share_pct, 2),
                "by_type": m.by_type,
                "by_month": m.by_month,
                "by_hour": m.by_hour,
                "preference_summary": m.preference_summary,
                "top_words": m.top_words,
                "top_emojis": m.top_emojis,
                "language_style": m.personality.language_style if m.personality else "",
                "personality_traits": m.personality.personality_traits if m.personality else [],
                "concern_summary": m.personality.concern_summary if m.personality else "",
                "top_concerns": m.personality.top_concerns if m.personality else [],
            }
            for m in members.values()
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        charts.append(json_path)

    print()
    print(f"[+] 报告与图表已保存到: {out_dir}")
    for p in [report_path, *charts]:
        print(f"    - {p.name}")
    return 0


def cmd_prepare(_args: argparse.Namespace) -> int:
    prepare_data(decrypted_dir=DEFAULT_DECRYPTED_DIR)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "groups": cmd_groups,
        "analyze": cmd_analyze,
        "prepare": cmd_prepare,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
