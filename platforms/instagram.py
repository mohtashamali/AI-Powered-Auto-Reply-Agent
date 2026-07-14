"""
instagram.py — Instagram DM platform connector.
Fetches unread DMs via Apify, sends replies back.
"""

import os
import sys
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apify_client import ApifyClient
from agents.brain import process_message
from memory.memory import has_replied, mark_replied, mark_skipped, add_to_human_queue
from utils.logger import get_logger

log = get_logger("instagram")
apify = ApifyClient(os.getenv("APIFY_TOKEN"))

PLATFORM = "instagram"
DELAY_MIN = int(os.getenv("REPLY_DELAY_MIN_SEC", 90))
DELAY_MAX = int(os.getenv("REPLY_DELAY_MAX_SEC", 300))


def fetch_unread_dms() -> list[dict]:
    """Fetch unread DMs using Apify Instagram DM Scraper."""
    log.info("Fetching unread Instagram DMs...")
    try:
        run = apify.actor("apify/instagram-dm-scraper").call(input={
            "username": os.getenv("IG_USERNAME"),
            "password": os.getenv("IG_PASSWORD"),
            "sessionCookie": os.getenv("IG_SESSION_COOKIE", ""),
            "onlyUnread": True,
            "maxConversations": 50,
        })
        items = list(apify.dataset(run["defaultDatasetId"]).iterate_items())
        log.info(f"Found {len(items)} unread conversations")
        return items
    except Exception as e:
        log.error(f"Failed to fetch DMs: {e}")
        return []


def send_reply(thread_id: str, reply_text: str) -> bool:
    """Send a reply to an Instagram DM thread."""
    try:
        apify.actor("apify/instagram-message-sender").call(input={
            "username": os.getenv("IG_USERNAME"),
            "password": os.getenv("IG_PASSWORD"),
            "threadId": thread_id,
            "message": reply_text,
        })
        return True
    except Exception as e:
        log.error(f"Failed to send reply to thread {thread_id}: {e}")
        return False


def run_instagram_agent(dry_run: bool = False):
    """
    Main Instagram agent loop.
    dry_run=True: detects intent and generates replies but does NOT send.
    """
    log.info("=" * 50)
    log.info("Instagram DM Agent starting")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    dms = fetch_unread_dms()
    if not dms:
        log.info("No unread DMs found. Agent done.")
        return

    stats = {"processed": 0, "replied": 0, "skipped": 0, "errors": 0, "human_queue": 0}

    for dm in dms:
        thread_id      = dm.get("threadId") or dm.get("id")
        sender_name    = dm.get("senderName") or dm.get("username", "Unknown")
        sender_handle  = dm.get("senderUsername") or dm.get("username", "unknown")
        message        = dm.get("lastMessage") or dm.get("message", "")
        history        = dm.get("messages", [])  # conversation history if available

        if not thread_id or not message:
            continue

        stats["processed"] += 1
        log.info(f"\n[{stats['processed']}] @{sender_handle}: \"{message[:80]}...\"")

        # Skip if already handled
        if has_replied(PLATFORM, thread_id):
            log.info("  → Already replied. Skipping.")
            continue

        # Process through AI brain
        try:
            result = process_message(
                sender_name=sender_name,
                message=message,
                platform=PLATFORM,
                conversation_history=history
            )
        except Exception as e:
            log.error(f"  → Brain error: {e}")
            stats["errors"] += 1
            continue

        if result.skip:
            reason = result.skip_reason or "unknown"
            log.info(f"  → Skipped: {reason}")

            if reason == "requires_human_review" and result.intent:
                add_to_human_queue(
                    PLATFORM, thread_id, sender_handle,
                    message, result.intent.intent, result.intent.key_ask
                )
                stats["human_queue"] += 1
                log.warning(f"  → Added to human queue (intent: {result.intent.intent})")
            else:
                mark_skipped(PLATFORM, thread_id, reason)
                stats["skipped"] += 1
            continue

        intent   = result.intent
        reply    = result.reply_text
        urgency  = intent.urgency

        log.info(f"  → Intent: {intent.intent} | Urgency: {urgency} | Lang: {intent.language}")
        log.info(f"  → Ask: {intent.key_ask}")
        log.info(f"  → Reply: \"{reply[:100]}...\"")

        if dry_run:
            log.info("  → DRY RUN: Not sending.")
            mark_replied(PLATFORM, thread_id, sender_handle, intent.intent, reply)
            stats["replied"] += 1
            continue

        # Human-like delay (urgent messages get faster response)
        if urgency == "high":
            delay = random.uniform(15, 45)
        else:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)

        log.info(f"  → Waiting {delay:.0f}s before sending...")
        time.sleep(delay)

        success = send_reply(thread_id, reply)
        if success:
            mark_replied(PLATFORM, thread_id, sender_handle, intent.intent, reply)
            stats["replied"] += 1
            log.info(f"  → Sent successfully to @{sender_handle}")
        else:
            stats["errors"] += 1

        # Brief pause between messages (avoid rate limits)
        time.sleep(random.uniform(3, 8))

    log.info("\n" + "=" * 50)
    log.info(f"Instagram agent complete: {stats}")
    return stats
