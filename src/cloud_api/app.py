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
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .auth import AuthenticatedUser, AuthStore
from .demo import DemoTextTooLongError, extract_and_search
from .email import EmailSender
from .oauth_store import OAuthStore

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from memory_core.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class RegisterRequest(BaseModel):
    email: str


class DemoRequest(BaseModel):
    text: str
    query: str | None = None


class DemoEntity(BaseModel):
    id: str
    name: str
    type: str


class DemoRelation(BaseModel):
    id: str
    subject_id: str
    predicate: str
    object_id: str


class DemoResponse(BaseModel):
    entities: list[DemoEntity]
    relations: list[DemoRelation]
    context: str | None = None


class RegisterResponse(BaseModel):
    user_id: str
    api_key: str  # shown once, at registration


class RegisterRequestSentResponse(BaseModel):
    message: str


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


def _send_email_or_503(email_sender: EmailSender, to: str, subject: str, body: str) -> None:
    """`EmailSender.send` talks to a real external provider (Resend) and can
    fail for reasons entirely outside this service's control -- a rejected
    recipient domain, a transient outage, a misconfigured API key. Left
    unguarded, that surfaced as a bare 500 with no detail (a real bug caught
    by the website team reproducing it against `/users/register/request`):
    Resend specifically rejects sending to RFC 2606 reserved domains like
    `example.com` -- exactly what every curl example in this project's docs
    uses as a placeholder -- so anyone copy-pasting the documented example
    verbatim hit this. Catching it here turns that into a clean, actionable
    error instead of an opaque crash, for that failure mode and any other
    provider-side one.

    503, not 502/504: this deployment sits behind Cloudflare, which
    silently replaces the *body* of an origin's 502/504 response with its
    own generic "error code: 502" page regardless of what the origin
    actually sent -- verified against this exact endpoint in production,
    where the detail message below came back as Cloudflare's boilerplate
    instead of reaching the client. 503 (and plain 4xx) pass through
    unmodified, which is the only way the caller actually sees this
    message rather than a useless substitute."""
    try:
        email_sender.send(to=to, subject=subject, body=body)
    except Exception:
        logger.exception("email_sender.send failed while sending to %s", to)
        raise HTTPException(
            status_code=503,
            detail=(
                "failed to send the email -- if you used a placeholder address like "
                "example.com/example.org, the mail provider rejects those; retry with "
                "a real, deliverable address"
            ),
        ) from None


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
    cors_allowed_origins: list[str] | None = None,
    demo_llm: LLMProvider | None = None,
    demo_embedder: object | None = None,
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

    `cors_allowed_origins` is a separate allowlist for actual browser CORS
    (the `Access-Control-Allow-Origin` response header + preflight `OPTIONS`
    handling on plain HTTP routes like `/users/register`) -- unrelated to
    the MCP transport's own Origin check above, which never sends CORS
    headers back. Without this, a browser-based signup form (spomory's own
    marketing site, `CORS_ALLOWED_ORIGINS` env var) gets no
    `Access-Control-Allow-Origin` header and the request is blocked by the
    browser before this service's route code ever runs, even though the
    same request works fine from curl or a non-browser client. Leaving it
    unset disables CORS entirely (same as today, before this parameter
    existed) rather than defaulting to an open `*` origin.

    `oauth_store` is required together with `oauth_mcp_server` -- it backs
    the `/oauth/login` and `/oauth/verify` routes that implement
    `SpomoryOAuthProvider.authorize`'s redirect target.

    `email_sender` is independent of `oauth_mcp_server`: passing it (with
    `oauth_base_url`, used the same way as below) mounts
    `POST /users/register/request` + `GET /users/register/verify`, an
    email-verified alternative to the plain `POST /users/register` above.
    Plain `/users/register` never confirms the caller actually controls the
    email they typed in -- the key goes straight back in the HTTP response
    to whoever asked, so it's fine for a developer curling their own email
    but not safe to put behind a public web form (anyone could type in
    someone else's email and get a working key against that person's
    account). The `/request`+`/verify` pair only ever hands out a key after
    a link mailed to that address is clicked, so registering requires
    actually reading mail sent there.
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

    if cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["content-type", "x-api-key"],
        )

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
    def register(req: RegisterRequest, request: Request) -> RegisterResponse:
        # request.client.host reflects the real client IP, not nginx's, only
        # because remote_main.py's uvicorn.run(proxy_headers=True,
        # forwarded_allow_ips="127.0.0.1") tells Starlette to trust nginx's
        # X-Forwarded-For -- without that this would rate-limit "127.0.0.1"
        # for every request.
        client_ip = request.client.host if request.client else "unknown"
        if not store.check_and_record_registration_attempt(req.email, client_ip):
            raise HTTPException(status_code=429, detail="too many registration attempts, try again later")
        issued = store.register_or_reissue_key(req.email)
        return RegisterResponse(user_id=issued.user_id, api_key=issued.raw_key)

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(enforce_quota)) -> dict[str, str]:  # noqa: B008
        store.record_usage(user.api_key_id, endpoint="/me")
        return {"user_id": user.user_id}

    if demo_llm is not None and demo_embedder is not None:

        @app.post("/demo/try", response_model=DemoResponse)
        def demo_try(req: DemoRequest, request: Request) -> DemoResponse:
            # Same IP-based reasoning as /users/register, but tighter (see
            # DEMO_RATE_LIMIT_PER_IP): this call costs a real LLM extraction
            # request and has no account behind it to hold accountable.
            client_ip = request.client.host if request.client else "unknown"
            if not store.check_and_record_demo_attempt(client_ip):
                raise HTTPException(status_code=429, detail="too many demo requests, try again later")
            try:
                result = extract_and_search(demo_llm, demo_embedder, req.text, req.query)
            except DemoTextTooLongError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
            except Exception:
                # Same rationale as _send_email_or_503: this calls a real
                # external LLM API that can fail for reasons outside this
                # service's control, and Cloudflare eats 502/504 bodies.
                logger.exception("demo extract_and_search failed")
                raise HTTPException(
                    status_code=503, detail="failed to process the demo request -- try again"
                ) from None
            return DemoResponse(**result)

    base_url = oauth_base_url.rstrip("/") if oauth_base_url else None

    if email_sender is not None:
        assert base_url is not None, "oauth_base_url is required alongside email_sender"

        @app.post("/users/register/request", response_model=RegisterRequestSentResponse)
        def request_registration_email(req: RegisterRequest, request: Request) -> RegisterRequestSentResponse:
            # Same abuse surface as plain /users/register (a script could
            # hammer this to spam an inbox or probe which emails already
            # have accounts), so it shares the same rate limiter/table.
            client_ip = request.client.host if request.client else "unknown"
            if not store.check_and_record_registration_attempt(req.email, client_ip):
                raise HTTPException(status_code=429, detail="too many registration attempts, try again later")
            token = store.create_registration_verification_token(req.email)
            # Absolute for the same reason as oauth_login_submit's
            # verify_url below: a mail client has no "current page" to
            # resolve a relative link against.
            verify_url = f"{base_url}/users/register/verify?token={token}"
            _send_email_or_503(
                email_sender,
                to=req.email,
                subject="Confirm your Spomory registration",
                body=(
                    "<p>Click to get your API key: "
                    f"<a href='{html.escape(verify_url)}'>{html.escape(verify_url)}</a></p>"
                ),
            )
            return RegisterRequestSentResponse(message="Check your email for a link to get your API key.")

        @app.get("/users/register/verify", response_class=HTMLResponse)
        def verify_registration_email(token: str = Query(...)) -> str:
            email = store.consume_registration_verification_token(token)
            if email is None:
                raise HTTPException(status_code=400, detail="invalid, expired, or already-used verification link")
            issued = store.register_or_reissue_key(email)
            return (
                "<p>Your API key (shown once -- save it now):</p>"
                f"<pre>{html.escape(issued.raw_key)}</pre>"
                "<p>Configure your MCP client with this as the <code>x-api-key</code> header "
                "on the <code>/mcp-apikey/</code> connection.</p>"
            )

    if oauth_mcp_server is not None:
        assert oauth_store is not None and email_sender is not None and base_url is not None, (
            "oauth_store, email_sender, and oauth_base_url are required alongside oauth_mcp_server"
        )

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
            verify_url = f"{base_url}/oauth/verify?token={magic_link_token}"
            _send_email_or_503(
                email_sender,
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
