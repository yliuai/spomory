"""Append-only audit log for data-deletion events (Epic 10.3).

Backs the "记忆主权" promise's verifiability: every true-delete (Epic 7.3)
should leave behind a tamper-evident record of when it happened and what
was removed, even though the underlying data itself is gone.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@dataclass
class AuditRecord:
    id: str
    event_type: str
    user_id: str
    detail: dict[str, object]
    created_at: str


class AuditLog:
    """Append-only by convention: this class exposes no update/delete methods."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_deletion(self, user_id: str, entities_deleted: int, relations_deleted: int) -> AuditRecord:
        record = AuditRecord(
            id=str(uuid.uuid4()),
            event_type="true_delete",
            user_id=user_id,
            detail={"entities_deleted": entities_deleted, "relations_deleted": relations_deleted},
            created_at=datetime.now(UTC).isoformat(),
        )
        self._conn.execute(
            "INSERT INTO audit_log (id, event_type, user_id, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (record.id, record.event_type, record.user_id, json.dumps(record.detail), record.created_at),
        )
        self._conn.commit()
        return record

    def query(self, user_id: str) -> list[AuditRecord]:
        rows = self._conn.execute(
            "SELECT id, event_type, user_id, detail, created_at FROM audit_log "
            "WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        return [
            AuditRecord(id=r[0], event_type=r[1], user_id=r[2], detail=json.loads(r[3]), created_at=r[4])
            for r in rows
        ]
