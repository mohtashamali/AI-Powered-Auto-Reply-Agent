import os
import sys
import argparse
import time
import json
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from utils.logger import get_logger
from memory.memory import get_stats, _conn

log = get_logger("main")

# ── Natural language command router ───────────────────────────────────────────
def parse_natural_command(command: str) -> list[str]:
    """Turn a natural language command into a list of platform names."""
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        system='Map the user command to platforms. Return JSON array only. '
               'Valid values: "instagram", "gmail", "whatsapp", "twitter", "all". '
               'Example: ["instagram"] or ["gmail","twitter"] or ["all"]',
        messages=[{"role": "user", "content": command}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    platforms = json.loads(raw)
    if "all" in platforms:
        return ["instagram", "gmail", "whatsapp", "twitter"]
    return platforms


# ── Platform runners ──────────────────────────────────────────────────────────
def run_platform(platform: str, dry_run: bool = False) -> dict:
    """Run the agent for a specific platform."""
    log.info(f"\n{'='*60}")
    log.info(f"  Running platform: {platform.upper()}")
    log.info(f"{'='*60}")

    try:
        if platform == "instagram":
            from platforms.instagram import run_instagram_agent
            return run_instagram_agent(dry_run=dry_run) or {}

        elif platform == "gmail":
            from platforms.gmail import run_gmail_agent
            return run_gmail_agent(dry_run=dry_run) or {}

        elif platform == "whatsapp":
            from platforms.whatsapp import run_whatsapp_agent
            return run_whatsapp_agent(dry_run=dry_run) or {}

        elif platform == "twitter":
            from platforms.twitter import run_twitter_agent
            return run_twitter_agent(dry_run=dry_run) or {}

        else:
            log.warning(f"Unknown platform: {platform}")
            return {}

    except ImportError as e:
        log.error(f"Missing dependency for {platform}: {e}")
        return {"error": str(e)}
    except Exception as e:
        log.error(f"Error running {platform}: {e}")
        return {"error": str(e)}


def run_all(dry_run: bool = False) -> dict:
    """Run all configured platforms."""
    platforms = []

    # Only include platforms that have credentials configured
    if os.getenv("APIFY_TOKEN") and os.getenv("IG_USERNAME"):
        platforms.append("instagram")
    if os.getenv("GMAIL_CREDENTIALS_JSON") or os.path.exists("./gmail_credentials.json"):
        platforms.append("gmail")
    if os.getenv("TWILIO_ACCOUNT_SID"):
        platforms.append("whatsapp")
    if os.getenv("TWITTER_API_KEY"):
        platforms.append("twitter")

    if not platforms:
        log.warning("No platforms configured. Set credentials in .env")
        return {}

    log.info(f"Running {len(platforms)} platforms: {', '.join(platforms)}")
    all_stats = {}
    for p in platforms:
        all_stats[p] = run_platform(p, dry_run=dry_run)
    return all_stats


# ── Dashboard ─────────────────────────────────────────────────────────────────
def show_dashboard():
    """Print a rich stats dashboard."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        console = Console()
    except ImportError:
        stats = get_stats()
        print(json.dumps(stats, indent=2))
        return

    stats = get_stats()

    console.print(Panel.fit(
        f"[bold]Personal Automation Agent[/bold] — Stats Dashboard",
        style="purple"
    ))

    # Summary
    summary = Table(box=box.SIMPLE)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Count", justify="right", style="white bold")
    summary.add_row("Total replied", str(stats["total_replied"]))
    summary.add_row("Total skipped", str(stats["total_skipped"]))
    summary.add_row("Pending human review", str(stats["pending_human_review"]))
    console.print(summary)

    # By platform
    if stats["by_platform"]:
        pt = Table(title="By platform", box=box.SIMPLE)
        pt.add_column("Platform", style="cyan")
        pt.add_column("Replied", justify="right")
        for platform, count in stats["by_platform"].items():
            pt.add_row(platform, str(count))
        console.print(pt)

    # By intent
    if stats["by_intent"]:
        it = Table(title="By intent", box=box.SIMPLE)
        it.add_column("Intent", style="cyan")
        it.add_column("Count", justify="right")
        for intent, count in list(stats["by_intent"].items())[:8]:
            it.add_row(intent, str(count))
        console.print(it)


def show_human_queue():
    """Show messages flagged for human review."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM human_queue WHERE resolved=0 ORDER BY queued_at DESC LIMIT 20"
        ).fetchall()

    if not rows:
        print("No messages in human queue.")
        return

    print(f"\n{'='*60}")
    print(f"  HUMAN REVIEW QUEUE ({len(rows)} items)")
    print(f"{'='*60}")
    for row in rows:
        print(f"\n[{row['id']}] {row['platform'].upper()} | {row['queued_at'][:16]}")
        print(f"  From: {row['sender']}")
        print(f"  Intent: {row['intent']} | Ask: {row['key_ask']}")
        print(f"  Message: {(row['message'] or '')[:120]}...")
        print(f"  → Reply manually, then mark resolved:")
        print(f"     python main.py --resolve {row['id']}")


def resolve_human(item_id: int):
    with _conn() as con:
        con.execute("UPDATE human_queue SET resolved=1 WHERE id=?", (item_id,))
        con.commit()
    print(f"Marked item #{item_id} as resolved.")


# ── Scheduler ─────────────────────────────────────────────────────────────────
def run_schedule(interval_minutes: int, dry_run: bool = False):
    """Run all platforms on a recurring schedule."""
    log.info(f"Scheduler started — running every {interval_minutes} minutes")
    while True:
        log.info(f"\n{'='*60}")
        log.info(f"  Scheduled run at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        run_all(dry_run=dry_run)
        log.info(f"  Next run in {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Personal Automation Agent")
    parser.add_argument("--platform",   help="Run a specific platform")
    parser.add_argument("--command",    help="Natural language command")
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--schedule",   action="store_true")
    parser.add_argument("--dashboard",  action="store_true")
    parser.add_argument("--human-queue",action="store_true", dest="human_queue")
    parser.add_argument("--resolve",    type=int, metavar="ID")
    parser.add_argument("--interval",   type=int, default=30,
                        help="Schedule interval in minutes (default: 30)")
    args = parser.parse_args()

    if args.dashboard:
        show_dashboard()

    elif args.human_queue:
        show_human_queue()

    elif args.resolve:
        resolve_human(args.resolve)

    elif args.schedule:
        run_schedule(args.interval, dry_run=args.dry_run)

    elif args.command:
        platforms = parse_natural_command(args.command)
        log.info(f"Command '{args.command}' → platforms: {platforms}")
        for p in platforms:
            run_platform(p, dry_run=args.dry_run)

    elif args.platform:
        run_platform(args.platform, dry_run=args.dry_run)

    else:
        run_all(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
