"""Epic 9.3: basic usage/retention event tracking.

Kept independent of `cloud_api/auth.py`'s usage table (which is
API-key-quota-scoped) — this one is keyed directly by user id and exists
purely to answer retention questions like "how many distinct users made at
least one call in the last 7 days", which the MCP server's local/no-auth
usage needs too, not just the cloud API.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class UsageTracker:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_event(self, user_id: str, event_type: str) -> None:
        self._conn.execute(
            "INSERT INTO usage_events (user_id, event_type, created_at) VALUES (?, ?, ?)",
            (user_id, event_type, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def active_users_since(self, days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        return row[0]

    def event_count(self, user_id: str, event_type: str | None = None) -> int:
        if event_type is None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE user_id = ?", (user_id,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE user_id = ? AND event_type = ?",
                (user_id, event_type),
            ).fetchone()
        return row[0]
