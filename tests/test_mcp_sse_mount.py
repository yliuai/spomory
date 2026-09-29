"""Regression coverage for the SSE mount added alongside the existing
Streamable HTTP one at /mcp-apikey (see `cloud_api/app.py`'s
`_mount_mcp_sse_app`): some platforms -- 阿里云百炼 (Alibaba Cloud Bailian)
is the concrete case that prompted this -- only speak the older SSE
transport and have no way to connect to a Streamable HTTP-only endpoint,
regardless of how a client config is written. Both mounts wrap the same
`MCPServer` instance, so a tool call's actual behavior (including the
x-api-key check inside remote.py's tools) is identical either way.

These tests check the mount is registered at the right path and doesn't
collide with the other two mounts, via `app.routes` rather than a live
HTTP request to the SSE endpoint itself: the MCP SDK's `sse_app()` handler
holds the ASGI connection open for the stream's lifetime by design, and
Starlette's synchronous `TestClient` (its ASGI calls run in a background
anyio "portal" thread) deadlocks trying to read a response from that kind
of long-lived, hand-rolled streaming handler -- confirmed to be a test-
harness limitation, not a bug in the mount itself, by running the exact
same app under a real `uvicorn` process and driving the actual SSE
protocol against it with `curl`: connecting returned a real
`event: endpoint` / `data: /mcp-apikey-sse/messages/?session_id=...` pair,
and POSTing a real `initialize` request to that message URL with a valid
`x-api-key` header produced a matching `event: message` reply
(`serverInfo.name` = `"Spomory"`) over the still-open GET stream --  a
genuine client (阿里云百炼 or otherwise) speaking real SSE against a real
deployment works end to end. That live smoke test isn't automated here
(no clean way to run a background uvicorn process from pytest without
flakiness of its own); the structural checks below are what's safe to
run on every test invocation.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient
from starlette.routing import Mount

from cloud_api.app import create_app
from cloud_api.auth import AuthStore


def _build_app(**extra):
    from memory_core.llm.base import TripleCandidate
    from memory_core.mcp_server.remote import build_remote_server
    from tests.test_incremental import FakeLLMProvider
    from tests.test_mcp_server import FakeEmbeddingProvider

    llm = FakeLLMProvider([TripleCandidate(subject="a", predicate="r", object="b", source_span="s")])
    auth_store = AuthStore(":memory:")
    remote_mcp_server = build_remote_server(auth_store, "postgresql://unused", llm, FakeEmbeddingProvider())
    return create_app(auth_store=auth_store, remote_mcp_server=remote_mcp_server, allowed_hosts=["testserver"], **extra)


def _mount_paths(app) -> set[str]:
    return {route.path for route in app.routes if isinstance(route, Mount)}


def test_sse_mount_is_registered_alongside_the_streamable_http_mount():
    app = _build_app()
    mounts = _mount_paths(app)
    assert "/mcp-apikey" in mounts
    assert "/mcp-apikey-sse" in mounts


def test_sse_mount_is_absent_when_no_remote_server_is_configured():
    """`remote_mcp_server=None` (the OAuth-only or bare-auth deployment
    shape) must not mount either the Streamable HTTP or the SSE app --
    both are gated on the same `remote_mcp_server is not None` check."""
    app = create_app(auth_store=AuthStore(":memory:"))
    mounts = _mount_paths(app)
    assert "/mcp-apikey" not in mounts
    assert "/mcp-apikey-sse" not in mounts


def test_streamable_http_mount_still_works_with_the_sse_mount_present():
    """The new mount is additive: a real POST /mcp-apikey/ initialize call
    -- the thing `test_oauth_mount_routing.py`'s coexistence test already
    covers without the SSE mount -- still succeeds now that a second mount
    sits alongside it."""
    app = _build_app()
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2026-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    }
    with TestClient(app) as client:
        resp = client.post(
            "/mcp-apikey/", headers={"Accept": "application/json, text/event-stream"}, json=init_body
        )
        assert resp.status_code == 200
