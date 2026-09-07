"""SpomoryOAuthProvider satisfies mcp.server.auth.provider
.OAuthAuthorizationServerProvider -- tested directly against the Protocol's
methods, independent of the SDK's routing layer (PKCE verification itself
happens inside the SDK before exchange_authorization_code is ever called,
so these tests exercise storage/expiry/one-time-use, not PKCE math)."""

import asyncio

import pytest

pytest.importorskip("mcp")

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull

from cloud_api.oauth_store import OAuthStore, SpomoryOAuthProvider, compute_pkce_challenge


def _client(client_id: str = "client-1") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id, redirect_uris=["https://client.example.com/callback"]
    )


def _params(code_verifier: str = "verifier") -> AuthorizationParams:
    return AuthorizationParams(
        state="xyz",
        scopes=["memory"],
        code_challenge=compute_pkce_challenge(code_verifier),
        redirect_uri="https://client.example.com/callback",
        redirect_uri_provided_explicitly=True,
    )


def test_register_and_get_client_round_trips():
    provider = SpomoryOAuthProvider(OAuthStore(":memory:"), login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    client = _client()

    asyncio.run(provider.register_client(client))
    fetched = asyncio.run(provider.get_client("client-1"))

    assert fetched is not None
    assert fetched.client_id == "client-1"
    assert asyncio.run(provider.get_client("nope")) is None


def test_authorize_stores_pending_request_and_redirects_to_login():
    provider = SpomoryOAuthProvider(OAuthStore(":memory:"), login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    client = _client()

    redirect = asyncio.run(provider.authorize(client, _params()))

    assert redirect.startswith("https://api.example.com/oauth/login?request_id=")


def test_full_flow_login_then_exchange_issues_tokens_bound_to_the_user():
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    client = _client()
    params = _params()

    request_id = store.create_pending_authorization(client.client_id, params)
    # simulate a completed magic-link login: create_authorization_code is what
    # cloud_api/app.py's GET /oauth/verify calls after the link is clicked.
    raw_code = store.create_authorization_code(client.client_id, "user-42", params)

    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))
    assert auth_code is not None
    assert auth_code.subject == "user-42"

    token = asyncio.run(provider.exchange_authorization_code(client, auth_code))
    assert token.access_token
    assert token.refresh_token

    access = asyncio.run(provider.load_access_token(token.access_token))
    assert access is not None
    assert access.subject == "user-42"
    assert access.client_id == client.client_id

    # one-time use: the same code can't be exchanged again
    assert asyncio.run(provider.load_authorization_code(client, raw_code)) is None
    del request_id  # only needed to seed the pending-authorization row above


def test_refresh_token_rotates_and_reissues_bound_to_the_same_user():
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    client = _client()
    params = _params()
    raw_code = store.create_authorization_code(client.client_id, "user-42", params)
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))
    first_tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))

    refresh = asyncio.run(provider.load_refresh_token(client, first_tokens.refresh_token))
    assert refresh is not None
    new_tokens = asyncio.run(provider.exchange_refresh_token(client, refresh, scopes=["memory"]))

    assert new_tokens.access_token != first_tokens.access_token
    new_access = asyncio.run(provider.load_access_token(new_tokens.access_token))
    assert new_access.subject == "user-42"
    # old refresh token was rotated out
    assert asyncio.run(provider.load_refresh_token(client, first_tokens.refresh_token)) is None


def test_revoke_token_invalidates_access_token():
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    client = _client()
    raw_code = store.create_authorization_code(client.client_id, "user-42", _params())
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))
    tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))

    access = asyncio.run(provider.load_access_token(tokens.access_token))
    asyncio.run(provider.revoke_token(access))

    assert asyncio.run(provider.load_access_token(tokens.access_token)) is None


def test_magic_link_is_one_time_use():
    store = OAuthStore(":memory:")
    request_id = store.create_pending_authorization("client-1", _params())
    token = store.create_magic_link("user-42", request_id)

    assert store.consume_magic_link(token) == ("user-42", request_id)
    assert store.consume_magic_link(token) is None  # can't be replayed


def _params_with_resource(resource: str, code_verifier: str = "verifier") -> AuthorizationParams:
    return AuthorizationParams(
        state="xyz",
        scopes=["memory"],
        code_challenge=compute_pkce_challenge(code_verifier),
        redirect_uri="https://client.example.com/callback",
        redirect_uri_provided_explicitly=True,
        resource=resource,
    )


def test_access_token_is_rejected_when_its_resource_does_not_match_this_server():
    """RFC 8707 audience check: a token minted (by this same authorization
    server) for a *different* resource must not be honored here -- the
    whole point of the resource parameter is to stop a token issued for
    service A from being replayed against service B. load_access_token is
    where this project enforces it, since the mcp SDK's own bearer-auth
    middleware doesn't (it only reads `.resource` for display, never
    compares it against anything itself)."""
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(
        store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp"
    )
    client = _client()
    raw_code = store.create_authorization_code(
        client.client_id, "user-42", _params_with_resource("https://other-service.example.com/mcp")
    )
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))

    tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))

    assert asyncio.run(provider.load_access_token(tokens.access_token)) is None


def test_access_token_is_accepted_when_its_resource_matches_this_server():
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(
        store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp"
    )
    client = _client()
    # trailing slash / differs from the configured resource_url -- must
    # still match via canonical-form comparison, not byte-for-byte, per
    # Anthropic's own connector docs on how Claude sends this value.
    raw_code = store.create_authorization_code(
        client.client_id, "user-42", _params_with_resource("https://api.example.com/mcp/")
    )
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))

    tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))

    access = asyncio.run(provider.load_access_token(tokens.access_token))
    assert access is not None
    assert access.subject == "user-42"


def test_access_token_with_no_resource_claim_is_accepted():
    """A client that never sends the (optional, per RFC 8707) resource
    parameter shouldn't have a mismatch invented against it."""
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(
        store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp"
    )
    client = _client()
    raw_code = store.create_authorization_code(client.client_id, "user-42", _params())  # no resource set
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))

    tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))

    assert asyncio.run(provider.load_access_token(tokens.access_token)) is not None


def test_refresh_preserves_the_original_resource_for_audience_checking():
    """The resource claim has to survive a refresh -- otherwise the very
    first exchange enforces the audience check but every subsequent
    refreshed token silently loses it."""
    store = OAuthStore(":memory:")
    provider = SpomoryOAuthProvider(
        store, login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp"
    )
    client = _client()
    raw_code = store.create_authorization_code(
        client.client_id, "user-42", _params_with_resource("https://other-service.example.com/mcp")
    )
    auth_code = asyncio.run(provider.load_authorization_code(client, raw_code))
    first_tokens = asyncio.run(provider.exchange_authorization_code(client, auth_code))

    refresh = asyncio.run(provider.load_refresh_token(client, first_tokens.refresh_token))
    new_tokens = asyncio.run(provider.exchange_refresh_token(client, refresh, scopes=["memory"]))

    # the refreshed token was still minted for the *other* service, so it
    # must still be rejected here, not silently accepted just because it
    # went through a refresh cycle.
    assert asyncio.run(provider.load_access_token(new_tokens.access_token)) is None
