"""User registration and API key issuance/validation.

Epic 10.2's requirement is designed in from the start: a key is shown in
plaintext exactly once (at creation) and only its hash is ever persisted,
so a database leak doesn't hand out working credentials.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
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
CREATE TABLE IF NOT EXISTS registration_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_registration_attempts_email ON registration_attempts(email);
CREATE INDEX IF NOT EXISTS idx_registration_attempts_ip ON registration_attempts(ip);
CREATE TABLE IF NOT EXISTS registration_verification_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
"""

# Same TTL as the OAuth login flow's magic link (oauth_store.py) -- long
# enough that a real inbox delay doesn't strand someone, short enough that
# a link sitting unread in an old email isn't usable indefinitely.
REGISTRATION_VERIFICATION_TTL_SECONDS = 900

# Deliberately generous: this exists to stop a script from hammering the
# endpoint (or enumerating/guessing emails), not to rate-limit a genuine
# user who registers once, loses the key, and tries again a few minutes
# later. Per-email is tighter than per-IP since one email being hit
# repeatedly is a stronger abuse signal than one IP (which may be a NAT/
# office network shared by many legitimate users) making a few calls.
REGISTRATION_RATE_LIMIT_PER_EMAIL = 5
REGISTRATION_RATE_LIMIT_PER_IP = 20
REGISTRATION_RATE_LIMIT_WINDOW = "-1 hours"


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
        """Unconditionally creates a *new* account -- raises `sqlite3.IntegrityError`
        on the `users.email` UNIQUE constraint if `email` is already registered.
        Kept for callers (tests, internal seeding) that want a guaranteed-fresh
        user_id per call with a distinct email each time; the public
        `/users/register` endpoint uses `register_or_reissue_key` instead so a
        real user re-registering the same email doesn't hit this crash."""
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

    def register_or_reissue_key(self, email: str) -> IssuedKey:
        """What both registration paths in `cloud_api.app` actually call:
        same email always resolves to the same `user_id` (via
        `find_or_create_user`) instead of `register_user`'s unconditional
        new-account insert, which used to crash with an unhandled
        `IntegrityError` on a second call with the same email -- not
        "silently create a second account" as it might look from the
        UNIQUE constraint alone, but a real 500 either way. Every call
        still issues a fresh key under that one account, so "I lost my
        key" is handled by registering again rather than by a separate
        recovery flow; old keys keep working until explicitly revoked.

        Plain `POST /users/register` calls this directly with no proof of
        email ownership -- anyone who types in an email they don't control
        gets a working key against whatever account it resolves to. The
        `/users/register/request` + `/users/register/verify` pair calls
        this only after `consume_registration_verification_token` confirms
        a link mailed to that address was actually clicked."""
        user_id = self.find_or_create_user(email)
        return self._issue_key(user_id)

    def create_registration_verification_token(self, email: str) -> str:
        """One-time link for `/users/register/verify`: the raw token is
        emailed to `email` and only its hash is stored (same pattern as API
        keys), so `register_or_reissue_key` never runs for this email until
        whoever received that email actually clicks it."""
        raw_token = secrets.token_urlsafe(32)
        self._conn.execute(
            "INSERT INTO registration_verification_tokens (token_hash, email, expires_at) VALUES (?, ?, ?)",
            (_hash_key(raw_token), email, time.time() + REGISTRATION_VERIFICATION_TTL_SECONDS),
        )
        self._conn.commit()
        return raw_token

    def consume_registration_verification_token(self, raw_token: str) -> str | None:
        """Returns the verified email and marks the token used (one-time,
        never replayable), or `None` if it's invalid, expired, or already
        used."""
        token_hash = _hash_key(raw_token)
        row = self._conn.execute(
            "SELECT email, expires_at, used FROM registration_verification_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None or row[2] or row[1] < time.time():
            return None
        self._conn.execute(
            "UPDATE registration_verification_tokens SET used = 1 WHERE token_hash = ?", (token_hash,)
        )
        self._conn.commit()
        return row[0]

    def check_and_record_registration_attempt(self, email: str, ip: str) -> bool:
        """Records this attempt and returns whether it's still within the
        rate limit -- called before the registration itself so a rejected
        attempt still counts toward the window (otherwise retrying past a
        429 would be free). Returns `False` once either the email or the IP
        has hit its limit within the last hour."""
        self._conn.execute(
            "INSERT INTO registration_attempts (email, ip) VALUES (?, ?)", (email, ip)
        )
        self._conn.commit()
        email_count = self._conn.execute(
            "SELECT COUNT(*) FROM registration_attempts WHERE email = ? AND created_at > datetime('now', ?)",
            (email, REGISTRATION_RATE_LIMIT_WINDOW),
        ).fetchone()[0]
        ip_count = self._conn.execute(
            "SELECT COUNT(*) FROM registration_attempts WHERE ip = ? AND created_at > datetime('now', ?)",
            (ip, REGISTRATION_RATE_LIMIT_WINDOW),
        ).fetchone()[0]
        return email_count <= REGISTRATION_RATE_LIMIT_PER_EMAIL and ip_count <= REGISTRATION_RATE_LIMIT_PER_IP

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
