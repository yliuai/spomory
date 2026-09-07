"""Regression coverage for a real routing bug: the SDK computes the
`/authorize`, `/token`, `/register`, `/revoke`, and
`/.well-known/oauth-authorization-server` URLs it advertises in its OAuth
metadata document purely from `issuer_url` as a string
(`mcp/server/auth/routes.py`'s `AUTHORIZATION_PATH` etc. are concatenated
onto it directly) -- it has no idea where the ASGI app implementing those
routes actually gets mounted. `issuer_url` has no path component (see
`cloud_api/remote_main.py`), so those routes have to be reachable at the
FastAPI app's root. An earlier version of `create_app` mounted the whole
OAuth-configured MCPServer under a "/mcp-oauth" prefix, which nested every
one of those routes under it too -- a real OAuth client fetching
"https://host/.well-known/oauth-authorization-server" (as computed from
issuer_url) would have 404'd even though "https://host/mcp-oauth/.well-known
/oauth-authorization-server" existed. These tests hit the real HTTP paths a
client would, not internal Python objects, so they'd have caught it.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from cloud_api.app import create_app
from cloud_api.auth import AuthStore
from cloud_api.email import FakeEmailSender
from cloud_api.oauth_store import OAuthStore, SpomoryOAuthProvider


def _app(allowed_origins=None, oauth_store=None):
    from memory_core.mcp_server.remote import build_oauth_remote_server

    oauth_store = oauth_store or OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(
        oauth_store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp"
    )
    oauth_mcp_server = build_oauth_remote_server(
        "postgresql://unused",
        llm=None,
        embedder=None,
        oauth_provider=provider,
        issuer_url="https://api.example.com",
        resource_server_url="https://api.example.com/mcp",
    )
    return create_app(
        auth_store=AuthStore(":memory:"),
        oauth_mcp_server=oauth_mcp_server,
        oauth_store=oauth_store,
        email_sender=FakeEmailSender(),
        oauth_base_url="https://api.example.com",
        allowed_hosts=["testserver"],
        allowed_origins=allowed_origins,
    )


def test_authorization_server_metadata_is_reachable_at_the_domain_root():
    with TestClient(_app()) as client:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        metadata = resp.json()
        # Every endpoint the metadata advertises must resolve at exactly
        # this URL, with no extra path prefix -- that's the whole bug.
        assert metadata["authorization_endpoint"] == "https://api.example.com/authorize"
        assert metadata["token_endpoint"] == "https://api.example.com/token"


def test_advertised_authorize_and_token_endpoints_are_actually_reachable_at_the_root():
    with TestClient(_app()) as client:
        # GET /authorize with no params 400s (missing required query params)
        # rather than 404 -- proves the route exists at the root, which is
        # what actually matters here (a 404 would mean it's nested under
        # some prefix instead, same bug as before).
        resp = client.get("/authorize")
        assert resp.status_code != 404

        resp = client.post("/token", data={})
        assert resp.status_code != 404


def test_oauth_resource_endpoint_is_reachable_at_its_own_path():
    with TestClient(_app()) as client:
        resp = client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2026-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        # 401 (missing bearer token) is fine and expected here -- what
        # matters is that the route exists (not 404) at exactly /mcp,
        # not nested under some other prefix.
        assert resp.status_code != 404


def test_existing_routes_are_not_shadowed_by_the_root_oauth_mount():
    """The OAuth app is mounted at "/" (path="/") last, specifically so it
    doesn't swallow requests meant for routes registered earlier -- this
    would silently break /users/register, /me, /oauth/login, /oauth/verify
    if mount ordering were ever wrong."""
    with TestClient(_app()) as client:
        resp = client.post("/users/register", json={"email": "a@example.com"})
        assert resp.status_code == 200

        resp = client.get("/oauth/login", params={"request_id": "nope"})
        assert resp.status_code == 400  # reaches the real handler, not a 404


def test_api_key_and_oauth_mounts_coexist_without_collision():
    """The whole reason the API-key mount lives at /mcp-apikey and the OAuth
    one at /mcp (not the reverse, and not both at /mcp): the OAuth mount's
    Connector URL needs to end in "mcp" (the convention real Connector
    Directory listings use), and only one of the two can occupy that exact
    path in one FastAPI app. This locks in that both are actually mounted
    and reachable at once, at their own distinct paths, with neither
    shadowing the other."""
    from cloud_api.auth import AuthStore
    from memory_core.llm.base import TripleCandidate
    from memory_core.mcp_server.remote import build_oauth_remote_server, build_remote_server
    from tests.test_incremental import FakeLLMProvider
    from tests.test_mcp_server import FakeEmbeddingProvider

    llm = FakeLLMProvider([TripleCandidate(subject="a", predicate="r", object="b", source_span="s")])
    remote_mcp_server = build_remote_server(AuthStore(":memory:"), "postgresql://unused", llm, FakeEmbeddingProvider())
    oauth_provider = SpomoryOAuthProvider(OAuthStore(":memory:"), login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    oauth_mcp_server = build_oauth_remote_server(
        "postgresql://unused",
        llm,
        FakeEmbeddingProvider(),
        oauth_provider,
        issuer_url="https://api.example.com",
        resource_server_url="https://api.example.com/mcp",
    )
    app = create_app(
        auth_store=AuthStore(":memory:"),
        remote_mcp_server=remote_mcp_server,
        oauth_mcp_server=oauth_mcp_server,
        oauth_store=OAuthStore(":memory:"),
        email_sender=FakeEmailSender(),
        oauth_base_url="https://api.example.com",
        allowed_hosts=["testserver"],
    )

    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2026-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    }
    headers = {"Accept": "application/json, text/event-stream"}

    with TestClient(app) as client:
        # /mcp-apikey needs no Authorization header -- it's the x-api-key mount
        resp = client.post("/mcp-apikey/", headers=headers, json=init_body)
        assert resp.status_code == 200

        # /mcp requires OAuth -- unauthenticated gets rejected by
        # RequireAuthMiddleware, not silently routed to the wrong mount
        resp = client.post("/mcp/", headers=headers, json=init_body)
        assert resp.status_code == 401

        # metadata discovery still lands at the root, unaffected by the
        # /mcp-apikey mount existing alongside it
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200


def _issue_real_access_token(oauth_store: OAuthStore, resource_url: str = "https://api.example.com/mcp") -> str:
    """Builds a real, valid Bearer token via the actual provider methods
    (register client, "complete" a login, exchange the code) -- needed
    because `RequireAuthMiddleware` checks the bearer token *before*
    `StreamableHTTPSessionManager` ever gets to check Origin/Host, so a
    request with no valid token 401s before Origin validation is even
    reached, regardless of what Origin it carries (confirmed by first
    writing this test against an unauthenticated request and watching an
    intentionally-bad Origin still come back 401, not 403)."""
    import asyncio

    provider = SpomoryOAuthProvider(
        oauth_store, login_base_url="https://api.example.com", resource_url=resource_url
    )
    client = OAuthClientInformationFull(
        client_id="test-client", redirect_uris=["https://client.example.com/callback"]
    )
    asyncio.run(provider.register_client(client))
    raw_code = oauth_store.create_authorization_code(
        client.client_id,
        "user-1",
        AuthorizationParams(
            state=None,
            scopes=["memory"],
            code_challenge="unused",
            redirect_uri="https://client.example.com/callback",
            redirect_uri_provided_explicitly=True,
        ),
    )
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))
    tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))
    return tokens.access_token


def test_origin_allowlist_admits_the_configured_origin_and_rejects_others():
    """Anthropic's own connector docs list 'overly strict Origin-header
    validation rejecting Anthropic's requests' as a documented cause of
    initialize failures during review -- leaving allowed_origins empty
    means *any* request carrying an Origin header gets rejected, which is
    the failure mode this guards against. A request with *no* Origin header
    at all (the common case for non-browser clients) must pass regardless,
    since DNS-rebinding protection only checks Origin when one is present.

    Needs a real valid Bearer token (see `_issue_real_access_token`) --
    without one, `RequireAuthMiddleware` 401s before
    `StreamableHTTPSessionManager`'s Origin/Host check is ever reached, so
    an unauthenticated request can't distinguish "bad Origin" from "no
    token" at all.
    """
    oauth_store = OAuthStore(":memory:")
    token = _issue_real_access_token(oauth_store)
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2026-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    }
    base_headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {token}"}

    with TestClient(_app(allowed_origins=["https://claude.ai"], oauth_store=oauth_store)) as client:
        resp = client.post("/mcp/", headers={**base_headers, "Origin": "https://claude.ai"}, json=init_body)
        assert resp.status_code != 403  # allowed origin: not rejected on Origin grounds

        resp = client.post(
            "/mcp/", headers={**base_headers, "Origin": "https://evil.example.com"}, json=init_body
        )
        assert resp.status_code == 403  # disallowed origin: rejected

        resp = client.post("/mcp/", headers=base_headers, json=init_body)  # no Origin header at all
        assert resp.status_code != 403
