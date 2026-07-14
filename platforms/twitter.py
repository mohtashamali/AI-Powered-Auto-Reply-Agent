"""
twitter.py — Twitter/X mentions and DM auto-reply connector.
Uses Tweepy v4 (Twitter API v2).
"""

import os
import sys
import time
import random
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.brain import process_message
from memory.memory import has_replied, mark_replied, mark_skipped, add_to_human_queue
from utils.logger import get_logger

log = get_logger("twitter")
PLATFORM = "twitter"

DELAY_MIN = int(os.getenv("REPLY_DELAY_MIN_SEC", 30))
DELAY_MAX = int(os.getenv("REPLY_DELAY_MAX_SEC", 180))


def get_tweepy_client():
    try:
        import tweepy
    except ImportError:
        raise ImportError("pip install tweepy")

    return tweepy.Client(
        bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
        consumer_key=os.getenv("TWITTER_API_KEY"),
        consumer_secret=os.getenv("TWITTER_API_SECRET"),
        access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
        access_token_secret=os.getenv("TWITTER_ACCESS_SECRET"),
        wait_on_rate_limit=True,
    )


def fetch_mentions(client, since_hours: int = 2) -> list[dict]:
    """Fetch recent mentions of your account."""
    import tweepy
    from datetime import datetime, timedelta, timezone

    me = client.get_me()
    user_id = me.data.id

    start_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    mentions = client.get_users_mentions(
        id=user_id,
        start_time=start_time,
        expansions=["author_id"],
        tweet_fields=["text", "author_id", "conversation_id", "in_reply_to_user_id"],
        user_fields=["username", "name"],
        max_results=20,
    )

    if not mentions.data:
        return []

    user_map = {u.id: u for u in (mentions.includes.get("users") or [])}
    result = []
    for tweet in mentions.data:
        author = user_map.get(tweet.author_id)
        result.append({
            "id": str(tweet.id),
            "conversation_id": str(tweet.conversation_id),
            "text": tweet.text,
            "author_id": str(tweet.author_id),
            "author_username": author.username if author else "unknown",
            "author_name": author.name if author else "Unknown",
        })

    log.info(f"Found {len(result)} mentions")
    return result


def reply_to_tweet(client, tweet_id: str, reply_text: str) -> bool:
    """Post a reply to a tweet."""
    try:
        # Twitter has a 280 char limit
        if len(reply_text) > 275:
            reply_text = reply_text[:272] + "..."
        client.create_tweet(
            text=reply_text,
            in_reply_to_tweet_id=tweet_id
        )
        return True
    except Exception as e:
        log.error(f"Failed to reply to tweet {tweet_id}: {e}")
        return False


def run_twitter_agent(dry_run: bool = False):
    """Main Twitter agent loop."""
    log.info("=" * 50)
    log.info(f"Twitter/X Agent starting | Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    client = get_tweepy_client()
    mentions = fetch_mentions(client)
    stats = {"processed": 0, "replied": 0, "skipped": 0, "errors": 0}

    for mention in mentions:
        tweet_id = mention["id"]
        sender   = mention["author_name"]
        handle   = mention["author_username"]
        text     = mention["text"]

        stats["processed"] += 1
        log.info(f"\n[{stats['processed']}] @{handle}: \"{text[:80]}\"")

        if has_replied(PLATFORM, tweet_id):
            log.info("  → Already replied. Skipping.")
            continue

        try:
            result = process_message(
                sender_name=f"{sender} (@{handle})",
                message=text,
                platform=PLATFORM,
            )
        except Exception as e:
            log.error(f"  → Brain error: {e}")
            stats["errors"] += 1
            continue

        if result.skip:
            mark_skipped(PLATFORM, tweet_id, result.skip_reason)
            if result.skip_reason == "requires_human_review" and result.intent:
                add_to_human_queue(
                    PLATFORM, tweet_id, handle,
                    text, result.intent.intent, result.intent.key_ask
                )
            stats["skipped"] += 1
            log.info(f"  → Skipped: {result.skip_reason}")
            continue

        intent = result.intent
        # Prepend @handle for Twitter replies
        reply  = f"@{handle} {result.reply_text}"

        log.info(f"  → Intent: {intent.intent} | Reply: \"{reply[:100]}\"")

        if not dry_run:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            log.info(f"  → Posting in {delay:.0f}s...")
            time.sleep(delay)
            success = reply_to_tweet(client, tweet_id, reply)
            if not success:
                stats["errors"] += 1
                continue

        mark_replied(PLATFORM, tweet_id, handle, intent.intent, reply)
        stats["replied"] += 1
        log.info("  → Posted.")
        time.sleep(random.uniform(5, 15))

    log.info(f"\nTwitter agent complete: {stats}")
    return stats
