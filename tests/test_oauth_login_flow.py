"""End-to-end HTTP test of the /oauth/login -> /oauth/verify flow that sits
behind SpomoryOAuthProvider.authorize's redirect target (cloud_api/app.py).
Uses a FakeEmailSender to capture the "sent" link instead of really
emailing -- this is the login step a real OAuth client (e.g. Claude
Desktop's browser-based authorize flow) would drive interactively; here it's
driven directly via TestClient to prove the handoff between the three
routes works end to end.
"""

import re
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient
from mcp.server.auth.provider import AuthorizationParams

from cloud_api.app import create_app
from cloud_api.auth import AuthStore
from cloud_api.email import FakeEmailSender
from cloud_api.oauth_store import OAuthStore, SpomoryOAuthProvider, compute_pkce_challenge


def _client(oauth_store: OAuthStore, email_sender: FakeEmailSender) -> TestClient:
    from memory_core.mcp_server.remote import build_oauth_remote_server

    # A dummy OAuth-mounted MCP server just to exercise create_app's wiring --
    # this test doesn't call any tool through it, only the login routes, so
    # PostgresGraphStore is never actually constructed (it's lazy, per-user_id,
    # inside _UserStores.resolve()).
    provider = SpomoryOAuthProvider(oauth_store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")

    oauth_mcp_server = build_oauth_remote_server(
        "postgresql://unused",  # never actually connected to in this test
        llm=None,
        embedder=None,
        oauth_provider=provider,
        issuer_url="https://api.example.com",
        resource_server_url="https://api.example.com/mcp",
    )
    app = create_app(
        auth_store=AuthStore(":memory:"),
        oauth_mcp_server=oauth_mcp_server,
        oauth_store=oauth_store,
        email_sender=email_sender,
        oauth_base_url="https://api.example.com",
        allowed_hosts=["testserver"],
    )
    return TestClient(app)


def test_login_form_rejects_unknown_request_id():
    with _client(OAuthStore(":memory:"), FakeEmailSender()) as client:
        resp = client.get("/oauth/login", params={"request_id": "does-not-exist"})
        assert resp.status_code == 400


def test_full_login_flow_redirects_back_to_client_with_a_code():
    oauth_store = OAuthStore(":memory:")
    email_sender = FakeEmailSender()

    params = AuthorizationParams(
        state="xyz",
        scopes=["memory"],
        code_challenge=compute_pkce_challenge("verifier"),
        redirect_uri="https://client.example.com/callback",
        redirect_uri_provided_explicitly=True,
    )
    request_id = oauth_store.create_pending_authorization("client-1", params)

    with _client(oauth_store, email_sender) as client:
        resp = client.get("/oauth/login", params={"request_id": request_id})
        assert resp.status_code == 200

        resp = client.post(
            "/oauth/login", data={"email": "person@example.com", "request_id": request_id}
        )
        assert resp.status_code == 200
        assert len(email_sender.sent) == 1
        to, _subject, body = email_sender.sent[0]
        assert to == "person@example.com"

        # Must be absolute (scheme + host), not a bare "/oauth/verify?...":
        # a real bug shipped with a relative link here, and email clients
        # have no "current page" to resolve a relative path against -- some
        # turned it into "http://oauth/verify?..." (reading "oauth" as a
        # bare hostname) instead of opening the real server at all. A regex
        # that only looked for the path (without anchoring the scheme+host)
        # would have passed against that broken link too, so this
        # deliberately requires the full absolute form.
        verify_url = re.search(r"https://api\.example\.com/oauth/verify\?token=[\w-]+", body)
        assert verify_url is not None, f"expected an absolute verify link in the email body, got: {body!r}"

        resp = client.get(verify_url.group(), follow_redirects=False)
        assert resp.status_code == 302
        redirect = urlparse(resp.headers["location"])
        assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == "https://client.example.com/callback"
        query = parse_qs(redirect.query)
        assert query["state"] == ["xyz"]
        assert "code" in query

        # same magic link can't be used twice
        resp = client.get(verify_url.group())
        assert resp.status_code == 400


def test_redirect_preserves_the_clients_own_query_params_on_its_callback_url():
    """Regression test for a real bug: the redirect was built by naively
    concatenating "?code=..." onto redirect_uri, which produces a malformed
    URL (two "?"s) whenever the OAuth client's own callback URL already has
    a query string of its own -- exactly what MCP Inspector's callback looks
    like in practice. The symptom wasn't an obvious error: Inspector's
    frontend showed "OAuth callback could not be matched -- could not
    determine which server started the OAuth flow", because state ended up
    in the wrong place rather than being cleanly absent. Fixed by using the
    SDK's own construct_redirect_uri(), which merges into an existing query
    string instead of blindly appending.
    """
    oauth_store = OAuthStore(":memory:")
    email_sender = FakeEmailSender()

    params = AuthorizationParams(
        state="xyz",
        scopes=["memory"],
        code_challenge=compute_pkce_challenge("verifier"),
        redirect_uri="http://localhost:6274/oauth/callback?transportType=streamable-http",
        redirect_uri_provided_explicitly=True,
    )
    request_id = oauth_store.create_pending_authorization("client-1", params)

    with _client(oauth_store, email_sender) as client:
        client.post("/oauth/login", data={"email": "person@example.com", "request_id": request_id})
        verify_url = re.search(r"https://api\.example\.com/oauth/verify\?token=[\w-]+", email_sender.sent[0][2])

        resp = client.get(verify_url.group(), follow_redirects=False)
        assert resp.status_code == 302

        redirect = urlparse(resp.headers["location"])
        assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == "http://localhost:6274/oauth/callback"
        query = parse_qs(redirect.query)
        # the client's own pre-existing query param must survive
        assert query["transportType"] == ["streamable-http"]
        # and the new ones must be added, not smuggled into some malformed
        # second "?code=...&state=..." tail
        assert query["state"] == ["xyz"]
        assert len(query["code"]) == 1
