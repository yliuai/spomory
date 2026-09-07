"""User registration and API key issuance/validation.

Epic 10.2's requirement is designed in from the start: a key is shown in
plaintext exactly once (at creation) and only its hash is ever persisted,
so a database leak doesn't hand out working credentials.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    key_hash TEXT UNIQUE NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id TEXT NOT NULL REFERENCES api_keys(id),
    endpoint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


@dataclass
class IssuedKey:
    user_id: str
    api_key_id: str
    raw_key: str  # only ever available here, at issuance time


@dataclass
class AuthenticatedUser:
    user_id: str
    api_key_id: str


class AuthStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def register_user(self, email: str) -> IssuedKey:
        user_id = str(uuid.uuid4())
        self._conn.execute("INSERT INTO users (id, email) VALUES (?, ?)", (user_id, email))
        return self._issue_key(user_id)

    def find_or_create_user(self, email: str) -> str:
        """Idempotent lookup for the OAuth magic-link login: same email
        always resolves to the same `user_id`, unlike `register_user` which
        unconditionally creates a new user and issues a fresh API key."""
        row = self._conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row is not None:
            return row[0]
        user_id = str(uuid.uuid4())
        self._conn.execute("INSERT INTO users (id, email) VALUES (?, ?)", (user_id, email))
        self._conn.commit()
        return user_id

    def _issue_key(self, user_id: str) -> IssuedKey:
        raw_key = f"mck_{secrets.token_urlsafe(32)}"
        api_key_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO api_keys (id, user_id, key_hash) VALUES (?, ?, ?)",
            (api_key_id, user_id, _hash_key(raw_key)),
        )
        self._conn.commit()
        return IssuedKey(user_id=user_id, api_key_id=api_key_id, raw_key=raw_key)

    def authenticate(self, raw_key: str) -> AuthenticatedUser | None:
        row = self._conn.execute(
            "SELECT id, user_id FROM api_keys WHERE key_hash = ? AND revoked = 0",
            (_hash_key(raw_key),),
        ).fetchone()
        if row is None:
            return None
        return AuthenticatedUser(api_key_id=row[0], user_id=row[1])

    def revoke_key(self, api_key_id: str) -> None:
        self._conn.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (api_key_id,))
        self._conn.commit()

    def record_usage(self, api_key_id: str, endpoint: str) -> None:
        self._conn.execute(
            "INSERT INTO usage_events (api_key_id, endpoint) VALUES (?, ?)",
            (api_key_id, endpoint),
        )
        self._conn.commit()

    def usage_count(self, api_key_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE api_key_id = ?", (api_key_id,)
        ).fetchone()
        return row[0]
