"""
gmail.py — Gmail platform connector.
Reads unread emails, classifies them, drafts replies or takes actions.
Uses Google Gmail API via OAuth2 credentials.
"""

import os
import sys
import base64
import json
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.brain import process_message
from memory.memory import has_replied, mark_replied, mark_skipped, add_to_human_queue
from utils.logger import get_logger

log = get_logger("gmail")
PLATFORM = "gmail"

# ── Gmail API setup ────────────────────────────────────────────────────────────
def get_gmail_service():
    """Build and return authenticated Gmail service."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Install Google packages: pip install google-auth google-auth-oauthlib "
            "google-auth-httplib2 google-api-python-client"
        )

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    creds = None
    token_path = os.getenv("GMAIL_TOKEN_JSON", "./gmail_token.json")
    creds_path = os.getenv("GMAIL_CREDENTIALS_JSON", "./gmail_credentials.json")

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_unread_emails(service, max_results: int = 30) -> list[dict]:
    """Fetch unread emails from inbox."""
    log.info("Fetching unread Gmail messages...")
    results = service.users().messages().list(
        userId="me",
        labelIds=["INBOX", "UNREAD"],
        maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}

        # Extract plain text body
        body = _extract_body(msg["payload"])

        emails.append({
            "id": msg_ref["id"],
            "thread_id": msg.get("threadId"),
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", ""),
            "reply_to": headers.get("Reply-To", headers.get("From", "")),
            "date": headers.get("Date", ""),
            "body": body[:3000],  # limit for token efficiency
            "labels": msg.get("labelIds", []),
        })

    log.info(f"Found {len(emails)} unread emails")
    return emails


def _extract_body(payload) -> str:
    """Recursively extract plain text from email payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


def send_email(service, to: str, subject: str, body: str,
               thread_id: str = None, message_id: str = None):
    """Send an email reply."""
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
    if message_id:
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id

    msg.attach(MIMEText(body, "plain"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    kwargs = {"userId": "me", "body": {"raw": raw}}
    if thread_id:
        kwargs["body"]["threadId"] = thread_id

    service.users().messages().send(**kwargs).execute()


def mark_as_read(service, msg_id: str):
    service.users().messages().modify(
        userId="me", id=msg_id,
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def apply_label(service, msg_id: str, label_name: str):
    """Apply a Gmail label (creates it if it doesn't exist)."""
    # Get or create label
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label_id = next((l["id"] for l in labels if l["name"] == label_name), None)

    if not label_id:
        new_label = service.users().labels().create(
            userId="me", body={"name": label_name}
        ).execute()
        label_id = new_label["id"]

    service.users().messages().modify(
        userId="me", id=msg_id,
        body={"addLabelIds": [label_id]}
    ).execute()


def run_gmail_agent(dry_run: bool = False):
    """Main Gmail agent loop."""
    log.info("=" * 50)
    log.info(f"Gmail Agent starting | Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    service = get_gmail_service()
    emails = fetch_unread_emails(service)

    if not emails:
        log.info("No unread emails. Done.")
        return

    stats = {"processed": 0, "replied": 0, "skipped": 0, "human_queue": 0, "errors": 0}

    for email in emails:
        msg_id    = email["id"]
        thread_id = email["thread_id"]
        sender    = email["from"]
        subject   = email["subject"]
        body      = email["body"]

        stats["processed"] += 1
        log.info(f"\n[{stats['processed']}] From: {sender[:50]}")
        log.info(f"  Subject: {subject[:60]}")

        if has_replied(PLATFORM, msg_id):
            log.info("  → Already handled. Skipping.")
            continue

        # Build message for brain (include subject for context)
        full_message = f"Subject: {subject}\n\n{body}"

        try:
            result = process_message(
                sender_name=sender,
                message=full_message,
                platform=PLATFORM,
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
                    PLATFORM, msg_id, sender,
                    body[:500], result.intent.intent, result.intent.key_ask
                )
                apply_label(service, msg_id, "Agent/NeedsReview")
                stats["human_queue"] += 1
            else:
                mark_skipped(PLATFORM, msg_id, reason)
                # Auto-label newsletters
                if reason == "spam":
                    apply_label(service, msg_id, "Agent/AutoFiltered")
            stats["skipped"] += 1
            mark_as_read(service, msg_id)
            continue

        intent = result.intent
        reply  = result.reply_text

        log.info(f"  → Intent: {intent.intent} | Urgency: {intent.urgency}")
        log.info(f"  → Reply preview: \"{reply[:80]}...\"")

        # Apply intent-based label
        label_map = {
            "collab_request": "Agent/Collab",
            "pricing_query": "Agent/Pricing",
            "customer_support": "Agent/Support",
            "job_offer": "Agent/Jobs",
        }
        label = label_map.get(intent.intent, "Agent/Replied")
        apply_label(service, msg_id, label)

        if not dry_run:
            delay = random.uniform(30, 120)
            log.info(f"  → Sending in {delay:.0f}s...")
            time.sleep(delay)

            send_email(
                service,
                to=email["reply_to"],
                subject=email["subject"],
                body=reply,
                thread_id=thread_id,
                message_id=msg_id
            )

        mark_replied(PLATFORM, msg_id, sender, intent.intent, reply)
        mark_as_read(service, msg_id)
        stats["replied"] += 1
        log.info(f"  → Done.")

    log.info(f"\nGmail agent complete: {stats}")
    return stats
