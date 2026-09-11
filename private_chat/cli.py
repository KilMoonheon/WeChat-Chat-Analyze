"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from private_chat.charts import generate_charts
from wechat_stats.config import (
    DEFAULT_DECRYPTED_DIR,
    PROJECT_ROOT,
    auto_detect_db_dir,
    ensure_work_dirs,
)
from wechat_stats.decrypt import prepare_data
from wechat_stats.reader import (
    collect_messages,
    detect_my_wxid,
    list_contacts_with_messages,
    load_contacts,
    resolve_contact,
)
from wechat_stats.personality import (
    PersonMessage,
    analyze_person,
    render_dual_report,
)
from private_chat.stats import compute_stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="微信聊天记录统计分析 — 统计与特定联系人的聊天频率、消息类型分布",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="提取密钥并解密微信数据库（需微信运行）")
    p_prepare.add_argument("--db-dir", type=Path, help="微信 db_storage 目录")
    p_prepare.add_argument("--decrypted-dir", type=Path, help="解密输出目录")

    p_contacts = sub.add_parser("contacts", help="列出所有有聊天记录的联系人")
    p_contacts.add_argument("--decrypted-dir", type=Path, default=DEFAULT_DECRYPTED_DIR)
    p_contacts.add_argument("--search", type=str, help="按名称搜索")

    p_analyze = sub.add_parser("analyze", help="分析指定联系人的聊天统计并生成图表")
    p_analyze.add_argument("contact", type=str, help="联系人备注/昵称/微信号")
    p_analyze.add_argument("--decrypted-dir", type=Path, default=DEFAULT_DECRYPTED_DIR)
    p_analyze.add_argument("--output", type=Path, default=PROJECT_ROOT / "output" / "private")

    return parser


def cmd_prepare(args: argparse.Namespace) -> int:
    prepare_data(db_dir=args.db_dir, decrypted_dir=args.decrypted_dir)
    return 0


def cmd_contacts(args: argparse.Namespace) -> int:
    decrypted_dir = Path(args.decrypted_dir)
    if not (decrypted_dir / "contact" / "contact.db").exists():
        print("未找到解密后的数据库。请先运行: python private_chat/main.py prepare")
        return 1

    contacts = load_contacts(decrypted_dir)
    items = list_contacts_with_messages(decrypted_dir, contacts)

    if args.search:
        q = args.search.lower()
        items = [(c, n) for c, n in items if q in c.display_name.lower() or q in c.remark.lower()]

    print(f"{'联系人':<20} {'类型':<6} {'消息数':>10}")
    print("-" * 40)
    for contact, count in items[:100]:
        kind = "群聊" if contact.is_group else "私聊"
        print(f"{contact.display_name:<20} {kind:<6} {count:>10,}")

    if len(items) > 100:
        print(f"\n... 共 {len(items)} 个联系人，仅显示前 100 个")
    else:
        print(f"\n共 {len(items)} 个联系人")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    decrypted_dir = Path(args.decrypted_dir)
    if not (decrypted_dir / "contact" / "contact.db").exists():
        print("未找到解密后的数据库。请先运行: python private_chat/main.py prepare")
        return 1

    contacts = load_contacts(decrypted_dir)
    contact = resolve_contact(args.contact, contacts)
    if not contact:
        print(f"未找到联系人: {args.contact}")
        print("提示: 运行 python private_chat/main.py contacts --search <关键词> 查看可用联系人")
        return 1

    print(f"[*] 正在分析: {contact.display_name} ({contact.username})")
    my_wxid = detect_my_wxid(decrypted_dir)
    messages = collect_messages(
        decrypted_dir, contact.username, my_wxid=my_wxid, include_content=True
    )
    if not messages:
        print("该联系人没有聊天记录（或消息未同步到 PC 端）")
        return 1

    stats = compute_stats(contact, messages)
    print()
    print(stats.summary_text())

    def _to_person(msgs: list) -> list[PersonMessage]:
        return [
            PersonMessage(type_name=m.type_name, create_time=m.create_time, text=m.text)
            for m in msgs
        ]

    my_msgs = [m for m in messages if m.is_sender]
    their_msgs = [m for m in messages if not m.is_sender]
    me_profile = analyze_person("我", _to_person(my_msgs))
    other_profile = analyze_person(contact.display_name, _to_person(their_msgs))
    personality_report = render_dual_report(
        me_profile, other_profile, title=f"私聊对象: {contact.display_name}"
    )
    print()
    print(personality_report)

    output_dir = Path(args.output) / contact.display_name.replace("/", "_")
    saved = generate_charts(stats, output_dir)
    personality_path = output_dir / f"{contact.display_name.replace('/', '_')}_性格与关注分析.txt"
    personality_path.write_text(personality_report, encoding="utf-8")
    saved.append(personality_path)

    print()
    print(f"[+] 图表已保存到: {output_dir}")
    for p in saved:
        print(f"    - {p.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_work_dirs()

    handlers = {
        "prepare": cmd_prepare,
        "contacts": cmd_contacts,
        "analyze": cmd_analyze,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
