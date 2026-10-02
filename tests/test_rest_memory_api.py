"""Tests for the plain REST surface over the six memory tools
(`/v1/memories`, `/v1/graph`, `/v1/export`): the counterpart to the MCP
mount for clients that can't speak MCP at all (Custom GPT Actions, no-code
automation). Mounting/auth is tested without a real Postgres (same trick
`test_oauth_mount_routing.py` uses: construct the per-user store cache
against an unused DSN -- `enforce_quota` rejects bad auth before any route
body ever calls `.resolve()` and actually connects); real tool-call
behavior needs a live database, same DATABASE_URL-gated pattern as
`test_remote_mcp_server.py`.
"""

import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient

from cloud_api.app import create_app
from cloud_api.auth import AuthStore

DATABASE_URL = os.environ.get("DATABASE_URL")


def _fake_llm():
    from memory_core.llm.base import TripleCandidate
    from tests.test_incremental import FakeLLMProvider

    return FakeLLMProvider([TripleCandidate(subject="张三", predicate="任职于", object="某公司", source_span="s")])


def _fake_embedder():
    from tests.test_mcp_server import FakeEmbeddingProvider

    return FakeEmbeddingProvider()


def _app(auth_store=None, mount_rest=True):
    from memory_core.mcp_server.remote import _UserStores

    auth_store = auth_store or AuthStore(":memory:")
    kwargs = {}
    if mount_rest:
        kwargs["rest_stores"] = _UserStores("postgresql://unused", _fake_llm())
        kwargs["rest_embedder"] = _fake_embedder()
    return create_app(auth_store=auth_store, **kwargs), auth_store


# --- mounting / auth, no real Postgres needed ---------------------------


def test_routes_not_mounted_without_rest_stores():
    client = TestClient(_app(mount_rest=False)[0])
    for method, path in [
        ("post", "/v1/memories"),
        ("get", "/v1/memories/search?query=x"),
        ("post", "/v1/memories/forget"),
        ("post", "/v1/memories/forget-all"),
        ("get", "/v1/graph?entity_name=x"),
        ("get", "/v1/export"),
    ]:
        resp = client.post(path, json={}) if method == "post" else client.get(path)
        assert resp.status_code == 404, f"{method} {path} should 404 when rest_stores is unset"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/memories", {"text": "x"}),
        ("get", "/v1/memories/search?query=x", None),
        ("post", "/v1/memories/forget", {"query": "x"}),
        ("post", "/v1/memories/forget-all", {}),
        ("get", "/v1/graph?entity_name=x", None),
        ("get", "/v1/export", None),
    ],
)
def test_missing_api_key_rejected(method, path, body):
    app, _ = _app()
    client = TestClient(app)
    resp = getattr(client, method)(path, json=body) if method == "post" else client.get(path)
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/memories", {"text": "x"}),
        ("get", "/v1/memories/search?query=x", None),
        ("post", "/v1/memories/forget", {"query": "x"}),
        ("post", "/v1/memories/forget-all", {}),
        ("get", "/v1/graph?entity_name=x", None),
        ("get", "/v1/export", None),
    ],
)
def test_wrong_api_key_rejected(method, path, body):
    app, _ = _app()
    client = TestClient(app)
    headers = {"x-api-key": "not-a-real-key"}
    resp = (
        getattr(client, method)(path, json=body, headers=headers)
        if method == "post"
        else client.get(path, headers=headers)
    )
    assert resp.status_code == 401


def test_authorization_bearer_header_works_as_an_alternative_to_x_api_key():
    """Why this exists: ChatGPT's Custom GPT Actions editor's standard "API
    Key" auth type only offers Bearer, no custom header name -- without this
    fallback, setting up a Custom GPT against this API would need a
    workaround on the GPT builder's side. Uses /me (no Postgres needed)
    rather than a /v1/memories route, since this is specifically testing
    `require_api_key`, not tool-call behavior."""
    auth_store = AuthStore(":memory:")
    key = auth_store.register_user("bearer-test@example.com").raw_key
    app, _ = _app(auth_store=auth_store, mount_rest=False)
    client = TestClient(app)

    resp = client.get("/me", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"]

    # x-api-key still works unchanged -- this is additive, not a replacement
    resp = client.get("/me", headers={"x-api-key": key})
    assert resp.status_code == 200


# --- real tool-call behavior, needs a live Postgres ----------------------

pytestmark_db = pytest.mark.skipif(not DATABASE_URL, reason="set DATABASE_URL to a real Postgres instance to run this")


def _db_app():
    from memory_core.mcp_server.remote import _UserStores

    auth_store = AuthStore(":memory:")
    key = auth_store.register_user("rest-test@example.com").raw_key
    app = create_app(
        auth_store=auth_store,
        rest_stores=_UserStores(DATABASE_URL, _fake_llm()),
        rest_embedder=_fake_embedder(),
    )
    return TestClient(app), key


def _truncate():
    from memory_core.graph.postgres_store import PostgresGraphStore

    PostgresGraphStore(DATABASE_URL, user_id="_cleanup")._conn.execute("TRUNCATE entities, relations")


@pytestmark_db
def test_add_then_search_round_trips_over_rest():
    client, key = _db_app()
    try:
        resp = client.post("/v1/memories", json={"text": "张三在某公司工作"}, headers={"x-api-key": key})
        assert resp.status_code == 200

        resp = client.get("/v1/memories/search", params={"query": "张三"}, headers={"x-api-key": key})
        assert resp.status_code == 200
        assert "张三任职于某公司" in resp.json()["result"]
    finally:
        _truncate()


@pytestmark_db
def test_forget_all_requires_explicit_confirm():
    client, key = _db_app()
    try:
        client.post("/v1/memories", json={"text": "张三在某公司工作"}, headers={"x-api-key": key})

        resp = client.post("/v1/memories/forget-all", headers={"x-api-key": key})
        assert resp.status_code == 200
        assert "张三" not in resp.json()["result"] or "删除" not in resp.json()["result"]

        still_there = client.get("/v1/memories/search", params={"query": "张三"}, headers={"x-api-key": key})
        assert "张三任职于某公司" in still_there.json()["result"]  # not deleted -- confirm defaulted to False

        resp = client.post(
            "/v1/memories/forget-all", params={"confirm": "true"}, headers={"x-api-key": key}
        )
        assert resp.status_code == 200

        gone = client.get("/v1/memories/search", params={"query": "张三"}, headers={"x-api-key": key})
        assert "没有找到相关记忆" in gone.json()["result"]
    finally:
        _truncate()


@pytestmark_db
def test_rest_calls_resolve_through_the_shared_user_stores_cache():
    """`remote_main.py` deploys this by passing `rest_stores=stores` -- the
    exact same `_UserStores` instance `build_remote_server(..., stores=stores)`
    uses for the MCP mount -- so a REST call and an MCP tool call against the
    same deployment resolve to the same cached `PostgresGraphStore` per
    `user_id`, not two separate connections. This checks that sharing
    directly at the `_UserStores` level (the unit both transports actually
    call `.resolve()` on), rather than driving a full MCP protocol session
    just to prove the same thing indirectly."""
    from memory_core.mcp_server.remote import _UserStores

    auth_store = AuthStore(":memory:")
    key = auth_store.register_user("shared-test@example.com").raw_key
    shared_stores = _UserStores(DATABASE_URL, _fake_llm())
    app = create_app(auth_store=auth_store, rest_stores=shared_stores, rest_embedder=_fake_embedder())
    client = TestClient(app)
    try:
        resp = client.post("/v1/memories", json={"text": "张三在某公司工作"}, headers={"x-api-key": key})
        assert resp.status_code == 200

        user = auth_store.authenticate(key)
        mcp_side_store, _ = shared_stores.resolve(user.user_id)
        assert len(mcp_side_store.all_relations()) == 1  # same cache entry the REST call just wrote through
    finally:
        _truncate()
