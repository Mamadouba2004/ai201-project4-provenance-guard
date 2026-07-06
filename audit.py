"""
audit.py — SQLite audit log for Provenance Guard.

Every /analyze request is stored with a timestamp, a text snippet (first 200 chars),
the final verdict, and the raw signal outputs.
"""

import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = "audit.db"


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            text_snippet TEXT   NOT NULL,
            prediction  TEXT    NOT NULL,
            confidence  REAL    NOT NULL,
            signals     TEXT    NOT NULL,
            text_length INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# Initialise on import
_init_db()


def log_request(text: str, result: dict) -> None:
    """Append one analysis result to the audit log."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO audit_log
            (timestamp, text_snippet, prediction, confidence, signals, text_length)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            text[:200],
            result["prediction"],
            result["confidence"],
            json.dumps(result["signals"]),
            result["text_length"],
        ),
    )
    conn.commit()
    conn.close()


def get_recent_logs(limit: int = 20) -> list[dict]:
    """Return the most recent audit entries (for the /logs endpoint)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
