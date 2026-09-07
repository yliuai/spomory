"""FastAPI cloud service: registration, API key auth, usage/rate limiting,
the remote multi-tenant MCP endpoint (Epic 11.5), and the OAuth 2.1 login
flow that sits in front of the OAuth-authenticated MCP mount.

Epic 8.1 built the auth/quota shell below; Epic 11.5 added mounting a
`remote.build_remote_server(...)` MCP server under `/mcp-apikey` on top of
it, so one deployed service handles both `POST /users/register` (get a
key) and the MCP connection itself. This module now also mounts a second,
OAuth-only MCP server as the Connector URL a client actually connects to
(see `memory_core.mcp_server.remote` for why it can't share the API-key
mount) and the three routes that implement the actual login step behind
`/authorize`: `mcp`'s own OAuth routes redirect here rather than
completing the flow themselves, since an authorization server has to make
a real human prove who they are before issuing a code.

`/mcp` (not `/mcp-apikey`) is reserved for the OAuth mount specifically
because that's the one submitted to Anthropic's Connector Directory, and
real-world Directory listings' Connector URLs conventionally end in `mcp`
-- the API-key mount's URL has no such external convention pressure (it's
only ever pasted into a client's own config by hand, not discovered
through a marketplace listing), so it's the one that got renamed instead
of reaching for a second subdomain just to keep both endings in "mcp".
"""

from __future__ import annotations

import html
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .auth import AuthenticatedUser, AuthStore
from .email import EmailSender
from .oauth_store import OAuthStore

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


class RegisterRequest(BaseModel):
    email: str


class RegisterResponse(BaseModel):
    user_id: str
    api_key: str  # shown once, at registration


def _mount_mcp_app(
    mcp_server: MCPServer,
    allowed_hosts: list[str] | None,
    streamable_http_path: str,
    allowed_origins: list[str] | None = None,
):
    """Builds the ASGI app for one MCPServer mount."""
    from mcp.server.transport_security import TransportSecuritySettings

    transport_security = (
        TransportSecuritySettings(allowed_hosts=allowed_hosts, allowed_origins=allowed_origins or [])
        if allowed_hosts
        else None
    )
    return mcp_server.streamable_http_app(
        streamable_http_path=streamable_http_path, transport_security=transport_security
    )


def create_app(
    auth_store: AuthStore | None = None,
    rate_limit_per_key: int = 1000,
    remote_mcp_server: MCPServer | None = None,
    oauth_mcp_server: MCPServer | None = None,
    oauth_store: OAuthStore | None = None,
    email_sender: EmailSender | None = None,
    oauth_base_url: str | None = None,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastAPI:
    """`allowed_hosts` is the MCP transport's DNS-rebinding-protection
    allowlist (checked against the request's `Host` header) -- it applies to
    both `remote_mcp_server` and `oauth_mcp_server`. Leaving it unset while
    mounting either rejects every request with 421, by design: this fails
    closed rather than silently accepting requests for whatever host the
    server happens to be reached at, so a real deployment must pass its
    actual public hostname(s) explicitly (see `cloud_api.remote_main`,
    `MCP_ALLOWED_HOSTS`).

    `allowed_origins` is the companion allowlist for the request's `Origin`
    header, checked only when a request actually carries one (most non-
    browser MCP clients -- Claude Desktop, curl, Cursor -- never send an
    Origin header at all, so this only matters for browser-based callers).
    Leaving it unset/empty means *any* request with an Origin header gets
    rejected, which is safe against arbitrary malicious sites but risks
    rejecting Claude's own legitimate traffic if it ever sends one --
    Anthropic's own connector docs list "overly strict Origin-header
    validation rejecting Anthropic's requests" as a documented cause of
    `initialize` failures during their review. Passing `["https://claude.ai"]`
    (see `MCP_ALLOWED_ORIGINS`) allows that one known-legitimate origin
    without weakening the check against anything else.

    `oauth_store`/`email_sender` are required together with
    `oauth_mcp_server` -- they back the `/oauth/login` and `/oauth/verify`
    routes that implement `SpomoryOAuthProvider.authorize`'s redirect target.
    """
    store = auth_store or AuthStore()

    remote_mcp_asgi_app = None
    if remote_mcp_server is not None:
        # streamable_http_path="/" so the "/mcp-apikey" mount prefix below
        # is the only copy of the path in the final route (the default
        # would double it up, e.g. /mcp-apikey/mcp).
        remote_mcp_asgi_app = _mount_mcp_app(
            remote_mcp_server, allowed_hosts, streamable_http_path="/", allowed_origins=allowed_origins
        )

    oauth_mcp_asgi_app = None
    if oauth_mcp_server is not None:
        # streamable_http_path="/mcp", and this app is mounted at the
        # FastAPI *root* below, NOT under a "/mcp" prefix. The SDK computes
        # the /authorize, /token, /register, /revoke, and
        # /.well-known/oauth-authorization-server URLs it advertises purely
        # from `issuer_url` (mcp/server/auth/routes.py: AUTHORIZATION_PATH
        # etc. are concatenated onto issuer_url as literal strings, with no
        # awareness of wherever this ASGI app happens to be mounted) --
        # issuer_url has no path component (see remote_main.py), so those
        # routes must actually be reachable at the domain root. Mounting
        # this app under a path prefix instead would nest every one of
        # those routes under it too, so a real client fetching the
        # metadata-advertised "https://host/authorize" would 404 even
        # though "https://host/<prefix>/authorize" existed.
        oauth_mcp_asgi_app = _mount_mcp_app(
            oauth_mcp_server, allowed_hosts, streamable_http_path="/mcp", allowed_origins=allowed_origins
        )

    mcp_asgi_apps = [a for a in (remote_mcp_asgi_app, oauth_mcp_asgi_app) if a is not None]

    lifespan = None
    if mcp_asgi_apps:

        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            # FastAPI/Starlette don't propagate lifespan startup into
            # mounted sub-apps automatically -- without entering each one's
            # lifespan_context, its MCP transport's session manager never
            # starts its task group and every tool call on that mount fails
            # with "Task group is not initialized."
            async with AsyncExitStack() as stack:
                for mcp_asgi_app in mcp_asgi_apps:
                    await stack.enter_async_context(mcp_asgi_app.router.lifespan_context(mcp_asgi_app))
                yield

    app = FastAPI(title="memory-core cloud API", lifespan=lifespan)

    def require_api_key(x_api_key: str = Header(...)) -> AuthenticatedUser:
        user = store.authenticate(x_api_key)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid or revoked API key")
        return user

    def enforce_quota(user: AuthenticatedUser = Depends(require_api_key)) -> AuthenticatedUser:  # noqa: B008
        if store.usage_count(user.api_key_id) >= rate_limit_per_key:
            raise HTTPException(status_code=429, detail="API key quota exceeded")
        return user

    @app.post("/users/register", response_model=RegisterResponse)
    def register(req: RegisterRequest) -> RegisterResponse:
        issued = store.register_user(req.email)
        return RegisterResponse(user_id=issued.user_id, api_key=issued.raw_key)

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(enforce_quota)) -> dict[str, str]:  # noqa: B008
        store.record_usage(user.api_key_id, endpoint="/me")
        return {"user_id": user.user_id}

    if oauth_mcp_server is not None:
        assert oauth_store is not None and email_sender is not None and oauth_base_url is not None, (
            "oauth_store, email_sender, and oauth_base_url are required alongside oauth_mcp_server"
        )
        oauth_base_url = oauth_base_url.rstrip("/")

        @app.get("/oauth/login", response_class=HTMLResponse)
        def oauth_login_form(request_id: str = Query(...)) -> str:
            if oauth_store.get_pending_authorization(request_id) is None:
                raise HTTPException(status_code=400, detail="unknown or expired authorization request")
            return (
                "<form method='post'>"
                "<label>Email: <input type='email' name='email' required></label>"
                f"<input type='hidden' name='request_id' value='{html.escape(request_id)}'>"
                "<button type='submit'>Send login link</button>"
                "</form>"
            )

        @app.post("/oauth/login", response_class=HTMLResponse)
        def oauth_login_submit(email: str = Form(...), request_id: str = Form(...)) -> str:
            if oauth_store.get_pending_authorization(request_id) is None:
                raise HTTPException(status_code=400, detail="unknown or expired authorization request")
            user_id = store.find_or_create_user(email)
            magic_link_token = oauth_store.create_magic_link(user_id, request_id)
            # Must be absolute: this link is opened directly from an email
            # client, which has no "current page" to resolve a relative path
            # against (a bare "/oauth/verify?..." was tried first and real
            # mail clients turned it into something like
            # "http://oauth/verify?..." -- "oauth" read as a bare hostname).
            verify_url = f"{oauth_base_url}/oauth/verify?token={magic_link_token}"
            email_sender.send(
                to=email,
                subject="Your Spomory login link",
                body=f"<p>Click to finish connecting: <a href='{html.escape(verify_url)}'>{html.escape(verify_url)}</a></p>",
            )
            return "<p>Check your email for a login link.</p>"

        @app.get("/oauth/verify")
        def oauth_verify(token: str = Query(...)) -> RedirectResponse:
            from mcp.server.auth.provider import construct_redirect_uri

            consumed = oauth_store.consume_magic_link(token)
            if consumed is None:
                raise HTTPException(status_code=400, detail="invalid, expired, or already-used login link")
            user_id, request_id = consumed
            pending = oauth_store.get_pending_authorization(request_id)
            if pending is None:
                raise HTTPException(status_code=400, detail="authorization request expired, please retry")
            client_id, params = pending
            code = oauth_store.create_authorization_code(client_id, user_id, params)
            # construct_redirect_uri (not naive string concatenation) merges
            # code/state into any query string redirect_uri already has and
            # percent-encodes them -- a client's own callback URL commonly
            # carries its own query params already (e.g. MCP Inspector's
            # does), and blindly appending "?code=..." to that produces a
            # second "?" and a malformed URL, which is exactly what was
            # breaking Inspector's "match this callback to a pending flow"
            # lookup (state was landing in the wrong place, not literally
            # missing).
            redirect_url = construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)
            return RedirectResponse(redirect_url, status_code=302)

    # Auth for /mcp-apikey tool calls happens inside remote.py's tools
    # themselves (x-api-key header); auth for /mcp happens in the SDK's own
    # RequireAuthMiddleware before the request reaches a tool at all.
    # Neither mount gates access at this layer.
    if remote_mcp_asgi_app is not None:
        app.mount("/mcp-apikey", remote_mcp_asgi_app)
    if oauth_mcp_asgi_app is not None:
        # Mounted at the root -- see the comment above on why its own
        # streamable_http_path="/mcp" (not this mount's prefix) is what
        # actually places the resource endpoint at /mcp. Registered last so
        # it doesn't shadow any of the routes/mounts above -- Starlette
        # matches in registration order, and this mount's path="/" would
        # otherwise catch everything.
        app.mount("/", oauth_mcp_asgi_app)

    app.state.auth_store = store
    return app


app = create_app()
