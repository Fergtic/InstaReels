#!/usr/bin/env python3
"""Dashboard script for viewing Reels engagement statistics."""

import argparse
from datetime import datetime
from database import Database

try:
    from tabulate import tabulate
    TABULATE_AVAILABLE = True
except ImportError:
    TABULATE_AVAILABLE = False


def format_table(data: list[dict], headers: list[str] = None) -> str:
    """Format data as a table."""
    if not data:
        return "No data available."

    if TABULATE_AVAILABLE:
        if headers:
            return tabulate(data, headers=headers, tablefmt="rounded_grid")
        return tabulate(data, headers="keys", tablefmt="rounded_grid")
    else:
        # Simple fallback formatting
        if not headers and data:
            headers = list(data[0].keys())

        # Calculate column widths
        widths = {h: len(str(h)) for h in headers}
        for row in data:
            for h in headers:
                val = str(row.get(h, ""))
                widths[h] = max(widths[h], len(val))

        # Build table
        lines = []
        header_line = " | ".join(str(h).ljust(widths[h]) for h in headers)
        lines.append(header_line)
        lines.append("-" * len(header_line))

        for row in data:
            row_line = " | ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers)
            lines.append(row_line)

        return "\n".join(lines)


def print_section(title: str, content: str):
    """Print a section with a title."""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)
    print(content)


def show_daily_digest(db: Database, days: int = 7):
    """Show daily stats digest."""
    stats = db.get_daily_stats(days)

    if not stats:
        print("No daily stats available yet.")
        return

    # Format for display
    formatted = []
    for s in stats:
        formatted.append({
            "Date": s["date"],
            "Analyzed": s["total_analyzed"],
            "Liked": s["total_liked"],
            "Commented": s["total_commented"],
            "Shared": s["total_shared"],
            "Avg Score": f"{s['avg_humor_score']:.1f}" if s["avg_humor_score"] else "N/A"
        })

    print_section(f"Daily Digest (Last {days} Days)", format_table(formatted))

    # Calculate totals
    total_analyzed = sum(s["total_analyzed"] for s in stats)
    total_liked = sum(s["total_liked"] for s in stats)
    total_commented = sum(s["total_commented"] for s in stats)
    total_shared = sum(s["total_shared"] for s in stats)

    print(f"\nTotals: {total_analyzed} analyzed, {total_liked} liked, "
          f"{total_commented} commented, {total_shared} shared")


def show_top_reels(db: Database, limit: int = 10):
    """Show top-rated reels."""
    reels = db.get_top_reels(limit)

    if not reels:
        print("No reels analyzed yet.")
        return

    formatted = []
    for r in reels:
        formatted.append({
            "Score": f"{r['humor_score']:.1f}",
            "Category": r["humor_category"] or "unknown",
            "Creator": f"@{r['username']}" if r["username"] else "unknown",
            "Caption": (r["caption"][:40] + "...") if r["caption"] and len(r["caption"]) > 40 else (r["caption"] or ""),
            "Action": r["action_taken"] or "none"
        })

    print_section(f"Top {limit} Highest-Rated Reels", format_table(formatted))

    # Show thumbnail URLs
    print("\nThumbnail URLs:")
    for i, r in enumerate(reels, 1):
        url = r.get("thumbnail_url", "N/A")
        print(f"  {i}. {url}")


def show_category_breakdown(db: Database):
    """Show engagement breakdown by humor category."""
    categories = db.get_category_breakdown()

    if not categories:
        print("No category data available yet.")
        return

    formatted = []
    for c in categories:
        formatted.append({
            "Category": c["humor_category"] or "unknown",
            "Count": c["count"],
            "Avg Score": f"{c['avg_score']:.1f}" if c["avg_score"] else "N/A",
            "Likes": c["likes"],
            "Comments": c["comments"],
            "Shares": c["shares"]
        })

    print_section("Engagement by Category", format_table(formatted))


def show_friend_stats(db: Database):
    """Show per-friend sharing statistics."""
    friends = db.get_friend_sharing_stats()

    if not friends:
        print("No sharing data available yet.")
        return

    formatted = []
    for f in friends:
        formatted.append({
            "Friend": f"@{f['friend_username']}",
            "Total Shares": f["total_shares"],
            "Last Shared": f["last_share_date"] or "N/A"
        })

    print_section("Friend Sharing Stats", format_table(formatted))


def show_recent_activity(db: Database, limit: int = 20):
    """Show recent engagement activity."""
    activity = db.get_recent_engagements(limit)

    if not activity:
        print("No recent activity.")
        return

    formatted = []
    for a in activity:
        timestamp = a["timestamp"]
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                timestamp = dt.strftime("%m/%d %H:%M")
            except Exception:
                pass

        formatted.append({
            "Time": timestamp,
            "Action": a["action_type"],
            "Score": f"{a['humor_score']:.1f}" if a.get("humor_score") else "N/A",
            "Category": a.get("humor_category", "")[:15] if a.get("humor_category") else "",
            "To": f"@{a['friend_username']}" if a.get("friend_username") else "",
            "Status": "OK" if a["success"] else "FAIL"
        })

    print_section(f"Recent Activity (Last {limit})", format_table(formatted))


def main():
    parser = argparse.ArgumentParser(
        description="Instagram Reels Auto-Engager Dashboard"
    )
    parser.add_argument(
        "--db", default="reels_data.db",
        help="Path to the database file"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Number of days for daily digest"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of top reels to show"
    )
    parser.add_argument(
        "--section", choices=["all", "digest", "top", "categories", "friends", "recent"],
        default="all",
        help="Which section to display"
    )

    args = parser.parse_args()

    db = Database(args.db)

    print("\n" + "=" * 60)
    print(" INSTAGRAM REELS AUTO-ENGAGER DASHBOARD")
    print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        if args.section in ["all", "digest"]:
            show_daily_digest(db, args.days)

        if args.section in ["all", "top"]:
            show_top_reels(db, args.top)

        if args.section in ["all", "categories"]:
            show_category_breakdown(db)

        if args.section in ["all", "friends"]:
            show_friend_stats(db)

        if args.section in ["all", "recent"]:
            show_recent_activity(db)

    finally:
        db.close()

    print("\n")


if __name__ == "__main__":
    main()
