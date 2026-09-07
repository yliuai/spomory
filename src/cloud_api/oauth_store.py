"""OAuth 2.1 + PKCE authorization server: storage plus the
`OAuthAuthorizationServerProvider` implementation the `mcp` SDK's routes
call into.

The SDK owns the wire protocol -- routing, RFC 7591 dynamic client
registration (it generates `client_id`/`client_secret` itself, we just
persist what it hands us), the `.well-known` metadata documents, and PKCE
verification at the token endpoint (`mcp/server/auth/handlers/token.py`
hashes the client's `code_verifier` and compares it against the stored
`code_challenge` *before* calling `exchange_authorization_code` below --
this provider does not need to, and does not have the verifier available
to re-check it). Everything else -- storage, expiry, and the actual
end-user login step behind `/authorize` -- is this module's job.

Login is a magic link, not a password: `authorize()` doesn't finish the
OAuth exchange itself, it stashes the request's `AuthorizationParams` under
a short-lived `request_id` and redirects the browser to `/oauth/login`
(cloud_api/app.py), which collects an email, emails a one-time link, and
only generates the real authorization code once that link is clicked
(`consume_magic_link` -> `create_authorization_code`).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

# Anthropic's Connector Directory review guide recommends short access
# tokens (limits blast radius if one leaks) and longer refresh tokens.
ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
AUTHORIZATION_CODE_TTL_SECONDS = 600
PENDING_AUTHORIZATION_TTL_SECONDS = 600
MAGIC_LINK_TTL_SECONDS = 900

_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_authorizations (
    request_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    params TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS magic_link_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    redirect_uri_provided_explicitly INTEGER NOT NULL,
    resource TEXT,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_access_tokens (
    token_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    resource TEXT,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    resource TEXT,
    expires_at REAL
);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RefreshTokenWithResource(RefreshToken):
    """The base `RefreshToken` model has no `resource` field (unlike
    `AccessToken`, which does) -- the Protocol's own docstring says it's
    fine to add fields on a subclass "which should not be exposed
    externally", which is exactly what this is for: carrying the RFC 8707
    resource through `exchange_refresh_token` so the *new* access token it
    issues on rotation still gets audience-checked against the same
    resource the original authorization was scoped to."""

    resource: str | None = None


class OAuthStore:
    """All storage the OAuth flow needs, in one SQLite file. Every token/code
    is stored as a hash (same pattern as `cloud_api.auth.AuthStore`) -- the
    raw value only ever exists in the response that hands it out."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- clients (RFC 7591 dynamic client registration) --

    def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self._conn.execute(
            "SELECT data FROM oauth_clients WHERE client_id = ?", (client_id,)
        ).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._conn.execute(
            "INSERT INTO oauth_clients (client_id, data) VALUES (?, ?) "
            "ON CONFLICT(client_id) DO UPDATE SET data = excluded.data",
            (client_info.client_id, client_info.model_dump_json()),
        )
        self._conn.commit()

    # -- pending authorizations: the /authorize -> /oauth/login handoff --

    def create_pending_authorization(self, client_id: str, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(24)
        self._conn.execute(
            "INSERT INTO pending_authorizations (request_id, client_id, params, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (
                request_id,
                client_id,
                params.model_dump_json(),
                time.time() + PENDING_AUTHORIZATION_TTL_SECONDS,
            ),
        )
        self._conn.commit()
        return request_id

    def get_pending_authorization(self, request_id: str) -> tuple[str, AuthorizationParams] | None:
        row = self._conn.execute(
            "SELECT client_id, params, expires_at FROM pending_authorizations WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None or row[2] < time.time():
            return None
        return row[0], AuthorizationParams.model_validate_json(row[1])

    # -- magic link login --

    def create_magic_link(self, user_id: str, request_id: str) -> str:
        raw_token = secrets.token_urlsafe(32)
        self._conn.execute(
            "INSERT INTO magic_link_tokens (token_hash, user_id, request_id, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_hash(raw_token), user_id, request_id, time.time() + MAGIC_LINK_TTL_SECONDS),
        )
        self._conn.commit()
        return raw_token

    def consume_magic_link(self, raw_token: str) -> tuple[str, str] | None:
        """Returns `(user_id, request_id)` and marks the link used, or `None`
        if it's invalid, expired, or already used (one-time use, never
        replayable)."""
        token_hash = _hash(raw_token)
        row = self._conn.execute(
            "SELECT user_id, request_id, expires_at, used FROM magic_link_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None or row[3] or row[2] < time.time():
            return None
        self._conn.execute("UPDATE magic_link_tokens SET used = 1 WHERE token_hash = ?", (token_hash,))
        self._conn.commit()
        return row[0], row[1]

    # -- authorization codes --

    def create_authorization_code(self, client_id: str, user_id: str, params: AuthorizationParams) -> str:
        raw_code = secrets.token_urlsafe(32)
        self._conn.execute(
            "INSERT INTO oauth_authorization_codes (code_hash, client_id, user_id, scopes, "
            "code_challenge, redirect_uri, redirect_uri_provided_explicitly, resource, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _hash(raw_code),
                client_id,
                user_id,
                json.dumps(params.scopes or []),
                params.code_challenge,
                str(params.redirect_uri),
                int(params.redirect_uri_provided_explicitly),
                params.resource,
                time.time() + AUTHORIZATION_CODE_TTL_SECONDS,
            ),
        )
        self._conn.commit()
        return raw_code

    def load_authorization_code(self, client_id: str, raw_code: str) -> AuthorizationCode | None:
        row = self._conn.execute(
            "SELECT client_id, user_id, scopes, code_challenge, redirect_uri, "
            "redirect_uri_provided_explicitly, resource, expires_at "
            "FROM oauth_authorization_codes WHERE code_hash = ?",
            (_hash(raw_code),),
        ).fetchone()
        if row is None or row[0] != client_id:
            return None
        return AuthorizationCode(
            code=raw_code,
            scopes=json.loads(row[2]),
            expires_at=row[7],
            client_id=row[0],
            code_challenge=row[3],
            redirect_uri=row[4],
            redirect_uri_provided_explicitly=bool(row[5]),
            resource=row[6],
            subject=row[1],
        )

    def consume_authorization_code(self, raw_code: str) -> None:
        """One-time use: delete on exchange so the same code can't be replayed."""
        self._conn.execute("DELETE FROM oauth_authorization_codes WHERE code_hash = ?", (_hash(raw_code),))
        self._conn.commit()

    # -- access / refresh tokens --

    def issue_tokens(
        self, client_id: str, user_id: str, scopes: list[str], resource: str | None = None
    ) -> tuple[str, str]:
        raw_access, raw_refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        self._conn.execute(
            "INSERT INTO oauth_access_tokens (token_hash, client_id, user_id, scopes, resource, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_hash(raw_access), client_id, user_id, json.dumps(scopes), resource, now + ACCESS_TOKEN_TTL_SECONDS),
        )
        self._conn.execute(
            "INSERT INTO oauth_refresh_tokens (token_hash, client_id, user_id, scopes, resource, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_hash(raw_refresh), client_id, user_id, json.dumps(scopes), resource, now + REFRESH_TOKEN_TTL_SECONDS),
        )
        self._conn.commit()
        return raw_access, raw_refresh

    def load_access_token(self, raw_token: str) -> AccessToken | None:
        row = self._conn.execute(
            "SELECT client_id, user_id, scopes, resource, expires_at FROM oauth_access_tokens WHERE token_hash = ?",
            (_hash(raw_token),),
        ).fetchone()
        if row is None or row[4] < time.time():
            return None
        return AccessToken(
            token=raw_token,
            client_id=row[0],
            scopes=json.loads(row[2]),
            expires_at=int(row[4]),
            subject=row[1],
            resource=row[3],
        )

    def load_refresh_token(self, client_id: str, raw_token: str) -> RefreshTokenWithResource | None:
        row = self._conn.execute(
            "SELECT client_id, user_id, scopes, resource, expires_at FROM oauth_refresh_tokens WHERE token_hash = ?",
            (_hash(raw_token),),
        ).fetchone()
        if row is None or row[0] != client_id or (row[4] is not None and row[4] < time.time()):
            return None
        return RefreshTokenWithResource(
            token=raw_token,
            client_id=row[0],
            scopes=json.loads(row[2]),
            expires_at=int(row[4]) if row[4] else None,
            subject=row[1],
            resource=row[3],
        )

    def revoke(self, raw_token: str) -> None:
        """Deletes whichever of the two tables holds this token -- an access
        or a refresh token can be handed in interchangeably, matching the
        Protocol's `revoke_token`."""
        token_hash = _hash(raw_token)
        self._conn.execute("DELETE FROM oauth_access_tokens WHERE token_hash = ?", (token_hash,))
        self._conn.execute("DELETE FROM oauth_refresh_tokens WHERE token_hash = ?", (token_hash,))
        self._conn.commit()

    def rotate_refresh_token(self, old_raw_token: str) -> None:
        self._conn.execute(
            "DELETE FROM oauth_refresh_tokens WHERE token_hash = ?", (_hash(old_raw_token),)
        )
        self._conn.commit()


def _normalize_resource(url: str) -> str:
    """Canonical form for RFC 8707 `resource` comparison: lowercase
    scheme+host, no trailing slash -- Anthropic's own connector docs note
    Claude sends the canonical form and expects the resource server to
    compare against that rather than doing a strict byte-for-byte match
    against whatever the client happened to send."""
    return url.rstrip("/").lower()


class SpomoryOAuthProvider:
    """Satisfies `mcp.server.auth.provider.OAuthAuthorizationServerProvider`
    (a `Protocol`, not a base class -- structural typing, nothing to call
    `super().__init__()` on)."""

    def __init__(self, store: OAuthStore, login_base_url: str, resource_url: str) -> None:
        self._store = store
        self._login_base_url = login_base_url.rstrip("/")
        self._resource_url = _normalize_resource(resource_url)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._store.get_client(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._store.register_client(client_info)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = self._store.create_pending_authorization(client.client_id, params)
        return f"{self._login_base_url}/oauth/login?request_id={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._store.load_authorization_code(client.client_id, authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # PKCE and expiry are already verified by mcp/server/auth/handlers/token.py
        # before this is called -- this just has to issue tokens and make sure
        # the code can never be exchanged a second time.
        self._store.consume_authorization_code(authorization_code.code)
        access_token, refresh_token = self._store.issue_tokens(
            client.client_id,
            authorization_code.subject or "",
            authorization_code.scopes,
            resource=authorization_code.resource,
        )
        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshTokenWithResource | None:
        return self._store.load_refresh_token(client.client_id, refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate both tokens on refresh, per the Protocol's own recommendation.
        self._store.rotate_refresh_token(refresh_token.token)
        granted_scopes = scopes or refresh_token.scopes
        resource = getattr(refresh_token, "resource", None)
        access_token, new_refresh_token = self._store.issue_tokens(
            client.client_id, refresh_token.subject or "", granted_scopes, resource=resource
        )
        return OAuthToken(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(granted_scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self._store.load_access_token(token)
        if access_token is None:
            return None
        # RFC 8707 audience check: only enforced when the token actually
        # carries a resource value -- clients aren't required to send the
        # (optional) resource parameter at /authorize, and we shouldn't
        # invent a mismatch against a token that never claimed one. When it
        # *is* present, mismatching it means this token was minted for a
        # different resource than the one being accessed and must not be
        # honored here (the whole point of RFC 8707: stop a token issued
        # for service A from being replayed against service B).
        if access_token.resource is not None and _normalize_resource(access_token.resource) != self._resource_url:
            return None
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._store.revoke(token.token)


def compute_pkce_challenge(code_verifier: str) -> str:
    """S256(code_verifier), for tests -- mirrors what
    `mcp/server/auth/handlers/token.py` computes to check a real client's
    code_verifier against the code_challenge stored at /authorize time."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
