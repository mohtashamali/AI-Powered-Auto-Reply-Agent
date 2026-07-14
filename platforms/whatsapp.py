"""
whatsapp.py — WhatsApp Business connector via Twilio.
Two modes:
  1. webhook_handler() — Flask webhook for real-time incoming messages
  2. run_whatsapp_agent() — Poll Twilio for recent messages (no webhook server needed)
"""

import os
import sys
import json
import time
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.brain import process_message
from memory.memory import has_replied, mark_replied, mark_skipped, add_to_human_queue
from utils.logger import get_logger

log = get_logger("whatsapp")
PLATFORM = "whatsapp"

DELAY_MIN = int(os.getenv("REPLY_DELAY_MIN_SEC", 10))
DELAY_MAX = int(os.getenv("REPLY_DELAY_MAX_SEC", 60))


def get_twilio_client():
    from twilio.rest import Client
    return Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )


def send_whatsapp(to: str, message: str) -> bool:
    """Send a WhatsApp message via Twilio."""
    try:
        client = get_twilio_client()
        client.messages.create(
            from_=os.getenv("TWILIO_WHATSAPP_FROM"),
            to=f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
            body=message
        )
        return True
    except Exception as e:
        log.error(f"Failed to send WhatsApp to {to}: {e}")
        return False


def fetch_recent_messages(hours: int = 2) -> list[dict]:
    """Fetch recent inbound WhatsApp messages from Twilio."""
    client = get_twilio_client()
    since = datetime.utcnow() - timedelta(hours=hours)

    messages = client.messages.list(
        to=os.getenv("TWILIO_WHATSAPP_FROM"),
        date_sent_after=since
    )

    result = []
    for msg in messages:
        if msg.direction == "inbound":
            result.append({
                "sid": msg.sid,
                "from": msg.from_.replace("whatsapp:", ""),
                "body": msg.body,
                "timestamp": str(msg.date_sent),
            })

    log.info(f"Found {len(result)} inbound WhatsApp messages")
    return result


def run_whatsapp_agent(dry_run: bool = False):
    """Poll-based WhatsApp agent."""
    log.info("=" * 50)
    log.info(f"WhatsApp Agent starting | Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    messages = fetch_recent_messages(hours=2)
    stats = {"processed": 0, "replied": 0, "skipped": 0, "errors": 0}

    for msg in messages:
        msg_id = msg["sid"]
        sender = msg["from"]
        text   = msg["body"]

        stats["processed"] += 1
        log.info(f"\n[{stats['processed']}] From: {sender}: \"{text[:60]}...\"")

        if has_replied(PLATFORM, msg_id):
            log.info("  → Already replied. Skipping.")
            continue

        try:
            result = process_message(
                sender_name=sender,
                message=text,
                platform=PLATFORM,
            )
        except Exception as e:
            log.error(f"  → Brain error: {e}")
            stats["errors"] += 1
            continue

        if result.skip:
            mark_skipped(PLATFORM, msg_id, result.skip_reason)
            if result.skip_reason == "requires_human_review" and result.intent:
                add_to_human_queue(
                    PLATFORM, msg_id, sender, text,
                    result.intent.intent, result.intent.key_ask
                )
                log.warning(f"  → Queued for human review")
            stats["skipped"] += 1
            continue

        reply = result.reply_text
        log.info(f"  → Intent: {result.intent.intent} | Reply: \"{reply[:80]}...\"")

        if not dry_run:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            log.info(f"  → Sending in {delay:.0f}s...")
            time.sleep(delay)
            success = send_whatsapp(sender, reply)
            if not success:
                stats["errors"] += 1
                continue

        mark_replied(PLATFORM, msg_id, sender, result.intent.intent, reply)
        stats["replied"] += 1
        log.info("  → Sent.")

    log.info(f"\nWhatsApp agent complete: {stats}")
    return stats


# ── Real-time webhook mode (run alongside Flask server) ───────────────────────
def create_webhook_app():
    """
    Returns a Flask app that handles Twilio WhatsApp webhooks in real-time.
    Deploy this to any server (Railway, Render, Heroku) and point
    Twilio's webhook URL to: https://your-server.com/whatsapp/webhook
    """
    try:
        from flask import Flask, request, Response
    except ImportError:
        raise ImportError("pip install flask")

    app = Flask(__name__)

    @app.route("/whatsapp/webhook", methods=["POST"])
    def webhook():
        sender  = request.form.get("From", "").replace("whatsapp:", "")
        message = request.form.get("Body", "")
        msg_sid = request.form.get("MessageSid", "")

        log.info(f"Webhook: {sender}: \"{message[:60]}\"")

        if not message or not sender:
            return Response("ok", 200)

        if has_replied(PLATFORM, msg_sid):
            return Response("ok", 200)

        try:
            result = process_message(sender, message, PLATFORM)

            if result.skip:
                mark_skipped(PLATFORM, msg_sid, result.skip_reason)
                if result.skip_reason == "requires_human_review" and result.intent:
                    add_to_human_queue(
                        PLATFORM, msg_sid, sender, message,
                        result.intent.intent, result.intent.key_ask
                    )
                return Response("ok", 200)

            # Small delay even in webhook mode (1-10s)
            time.sleep(random.uniform(1, 10))
            send_whatsapp(sender, result.reply_text)
            mark_replied(PLATFORM, msg_sid, sender,
                         result.intent.intent, result.reply_text)

        except Exception as e:
            log.error(f"Webhook error: {e}")

        return Response("ok", 200)

    @app.route("/health")
    def health():
        return {"status": "ok", "platform": "whatsapp"}

    return app
