"""
memory.py — Persistent memory so the agent never double-replies.
Uses a simple SQLite database. One table, works for all platforms.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "agent.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Create tables if they don't exist."""
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS replied (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                platform    TEXT NOT NULL,
                thread_id   TEXT NOT NULL,
                sender      TEXT,
                intent      TEXT,
                reply_text  TEXT,
                replied_at  TEXT NOT NULL,
                UNIQUE(platform, thread_id)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS skipped (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                platform    TEXT NOT NULL,
                thread_id   TEXT NOT NULL,
                reason      TEXT,
                skipped_at  TEXT NOT NULL,
                UNIQUE(platform, thread_id)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS human_queue (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                platform    TEXT NOT NULL,
                thread_id   TEXT NOT NULL,
                sender      TEXT,
                message     TEXT,
                intent      TEXT,
                key_ask     TEXT,
                queued_at   TEXT NOT NULL,
                resolved    INTEGER DEFAULT 0
            )
        """)
        con.commit()


def has_replied(platform: str, thread_id: str) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM replied WHERE platform=? AND thread_id=?",
            (platform, thread_id)
        ).fetchone()
        return row is not None


def mark_replied(platform: str, thread_id: str, sender: str,
                 intent: str, reply_text: str):
    with _conn() as con:
        con.execute("""
            INSERT OR IGNORE INTO replied (platform, thread_id, sender, intent, reply_text, replied_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (platform, thread_id, sender, intent, reply_text,
              datetime.utcnow().isoformat()))
        con.commit()


def mark_skipped(platform: str, thread_id: str, reason: str):
    with _conn() as con:
        con.execute("""
            INSERT OR IGNORE INTO skipped (platform, thread_id, reason, skipped_at)
            VALUES (?, ?, ?, ?)
        """, (platform, thread_id, reason, datetime.utcnow().isoformat()))
        con.commit()


def add_to_human_queue(platform: str, thread_id: str, sender: str,
                       message: str, intent: str, key_ask: str):
    with _conn() as con:
        con.execute("""
            INSERT INTO human_queue
            (platform, thread_id, sender, message, intent, key_ask, queued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (platform, thread_id, sender, message, intent, key_ask,
              datetime.utcnow().isoformat()))
        con.commit()


def get_stats() -> dict:
    with _conn() as con:
        total_replied = con.execute("SELECT COUNT(*) FROM replied").fetchone()[0]
        total_skipped = con.execute("SELECT COUNT(*) FROM skipped").fetchone()[0]
        pending_human = con.execute(
            "SELECT COUNT(*) FROM human_queue WHERE resolved=0"
        ).fetchone()[0]
        by_platform = con.execute(
            "SELECT platform, COUNT(*) as cnt FROM replied GROUP BY platform"
        ).fetchall()
        by_intent = con.execute(
            "SELECT intent, COUNT(*) as cnt FROM replied GROUP BY intent ORDER BY cnt DESC"
        ).fetchall()
    return {
        "total_replied": total_replied,
        "total_skipped": total_skipped,
        "pending_human_review": pending_human,
        "by_platform": {r["platform"]: r["cnt"] for r in by_platform},
        "by_intent": {r["intent"]: r["cnt"] for r in by_intent},
    }


# Initialise on import
init_db()
