"""
audit.py — SQLite audit log for Provenance Guard.

Every /submit request is stored with a timestamp, content_id, creator_id,
a text snippet (first 200 chars), the final verdict, individual signal
scores, and the raw signal outputs. Appeal events are logged separately
via log_appeal_event (Milestone 5).
"""

import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = "audit.db"


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id         TEXT    NOT NULL,
            creator_id         TEXT,
            timestamp          TEXT    NOT NULL,
            text_snippet       TEXT    NOT NULL,
            attribution        TEXT    NOT NULL,
            prediction         TEXT    NOT NULL,
            confidence         REAL    NOT NULL,
            llm_score          REAL,
            stylometric_score  REAL,
            signals            TEXT    NOT NULL,
            text_length        INTEGER NOT NULL,
            status             TEXT    NOT NULL DEFAULT 'classified'
        )
    """)
    conn.commit()
    conn.close()


# Initialise on import
_init_db()


def log_request(content_id: str, creator_id: str, text: str, result: dict) -> None:
    """Append one analysis result to the audit log."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO audit_log
            (content_id, creator_id, timestamp, text_snippet, attribution,
             prediction, confidence, llm_score, stylometric_score, signals,
             text_length, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_id,
            creator_id,
            datetime.now(timezone.utc).isoformat(),
            text[:200],
            result["attribution"],
            result["prediction"],
            result["confidence"],
            result["llm_score"],
            result["stylometric_score"],
            json.dumps(result["signals"]),
            result["text_length"],
            "classified",
        ),
    )
    conn.commit()
    conn.close()


def get_recent_logs(limit: int = 20) -> list[dict]:
    """Return the most recent audit entries (for the /log endpoint)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
