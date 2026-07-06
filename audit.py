"""
audit.py — SQLite audit log for Provenance Guard.

Every /submit request is stored with a timestamp, content_id, creator_id,
a text snippet (first 200 chars), the final verdict, individual signal
scores, and the raw signal outputs. When an appeal is filed (/appeal), the
same row is updated in place — status flips to 'under_review' and the
creator's reasoning is recorded — so the audit log always ties an appeal
back to the original classification decision.
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
            status             TEXT    NOT NULL DEFAULT 'classified',
            appeal_reasoning   TEXT,
            appealed_at        TEXT
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


def get_by_content_id(content_id: str) -> dict | None:
    """Return the audit entry for a given content_id, or None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM audit_log WHERE content_id = ? LIMIT 1", (content_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def log_appeal(content_id: str, creator_reasoning: str) -> bool:
    """
    Record an appeal against a prior classification.

    Updates the original audit row in place: status -> 'under_review',
    stores the creator's reasoning and the appeal timestamp. Returns False
    if no submission with this content_id exists.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        UPDATE audit_log
           SET status = 'under_review',
               appeal_reasoning = ?,
               appealed_at = ?
         WHERE content_id = ?
        """,
        (creator_reasoning, datetime.now(timezone.utc).isoformat(), content_id),
    )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated
