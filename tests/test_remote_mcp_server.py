"""Epic 11.5: the remote/HTTP MCP server authenticates per call by API key
and isolates tenants' memories via PostgresGraphStore's user_id scoping --
skipped without DATABASE_URL, same gating as test_postgres_store.py.
"""

import asyncio
import os

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("mcp")
pytest.importorskip("fastapi")

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set DATABASE_URL to a real Postgres instance to run this"
)


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class _FakeRequestContext:
    def __init__(self, headers):
        self.request = _FakeRequest(headers)


def _context(headers=None):
    """A minimal stand-in for the real HTTP-transport-populated Context --
    only `ctx.headers` is exercised by remote.py's tools, so this only needs
    to satisfy that one property."""
    from mcp.server.mcpserver import Context

    return Context(request_context=_FakeRequestContext(headers or {}))


def _build_server(auth_store, **kwargs):
    from memory_core.llm.base import TripleCandidate
    from memory_core.mcp_server.remote import build_remote_server
    from tests.test_incremental import FakeLLMProvider
    from tests.test_mcp_server import FakeEmbeddingProvider

    llm = FakeLLMProvider(
        [TripleCandidate(subject="张三", predicate="任职于", object="某公司", source_span="s")]
    )
    return build_remote_server(auth_store, DATABASE_URL, llm, FakeEmbeddingProvider(), **kwargs)


def _truncate():
    from memory_core.graph.postgres_store import PostgresGraphStore

    PostgresGraphStore(DATABASE_URL, user_id="_cleanup")._conn.execute(
        "TRUNCATE entities, relations"
    )


def test_missing_api_key_is_rejected():
    from cloud_api.auth import AuthStore

    server = _build_server(AuthStore(":memory:"))

    with pytest.raises(Exception):  # noqa: B017 - wrapped PermissionError from the tool body
        asyncio.run(server.call_tool("add_memory", {"text": "x"}, context=_context()))


def test_invalid_api_key_is_rejected():
    from cloud_api.auth import AuthStore

    server = _build_server(AuthStore(":memory:"))

    with pytest.raises(Exception):  # noqa: B017
        asyncio.run(
            server.call_tool(
                "add_memory", {"text": "x"}, context=_context({"x-api-key": "not-a-real-key"})
            )
        )


def test_two_api_keys_see_isolated_memories():
    from cloud_api.auth import AuthStore

    auth_store = AuthStore(":memory:")
    key_a = auth_store.register_user("a@example.com").raw_key
    key_b = auth_store.register_user("b@example.com").raw_key
    server = _build_server(auth_store)

    try:
        asyncio.run(
            server.call_tool(
                "add_memory",
                {"text": "张三在某公司工作"},
                context=_context({"x-api-key": key_a}),
            )
        )

        result_a = asyncio.run(
            server.call_tool(
                "search_memory", {"query": "张三"}, context=_context({"x-api-key": key_a})
            )
        )
        assert "张三任职于某公司" in str(result_a)

        result_b = asyncio.run(
            server.call_tool(
                "search_memory", {"query": "张三"}, context=_context({"x-api-key": key_b})
            )
        )
        assert "没有找到相关记忆" in str(result_b)
    finally:
        _truncate()


def test_oauth_authenticated_tool_call_resolves_to_the_tokens_subject():
    """The OAuth mount's counterpart to test_two_api_keys_see_isolated_memories:
    a real tool call authenticated via a Bearer access token (not x-api-key)
    resolves to the same per-user_id Postgres store, proving
    build_oauth_remote_server's resolve_user_id wiring works against a real
    database, not just the mocked contextvar unit tests in
    test_remote_oauth_context.py.
    """
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    from cloud_api.oauth_store import OAuthStore, SpomoryOAuthProvider
    from memory_core.llm.base import TripleCandidate
    from memory_core.mcp_server.remote import build_oauth_remote_server
    from tests.test_incremental import FakeLLMProvider
    from tests.test_mcp_server import FakeEmbeddingProvider

    llm = FakeLLMProvider(
        [TripleCandidate(subject="张三", predicate="任职于", object="某公司", source_span="s")]
    )
    provider = SpomoryOAuthProvider(OAuthStore(":memory:"), login_base_url="https://api.example.com", resource_url="https://api.example.com/mcp")
    server = build_oauth_remote_server(
        DATABASE_URL,
        llm,
        FakeEmbeddingProvider(),
        provider,
        issuer_url="https://api.example.com",
        resource_server_url="https://api.example.com/mcp-oauth",
    )

    access_token = AccessToken(token="t", client_id="oauth-client", scopes=["memory"], subject="oauth-user-1")
    ctx_token = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        asyncio.run(server.call_tool("add_memory", {"text": "张三在某公司工作"}, context=_context()))
        result = asyncio.run(server.call_tool("search_memory", {"query": "张三"}, context=_context()))
        assert "张三任职于某公司" in str(result)
    finally:
        auth_context_var.reset(ctx_token)
        _truncate()


def test_usage_and_audit_are_recorded_under_the_resolved_user_id():
    from cloud_api.auth import AuthStore
    from memory_core.audit import AuditLog
    from memory_core.usage import UsageTracker

    auth_store = AuthStore(":memory:")
    issued = auth_store.register_user("c@example.com")
    usage_tracker = UsageTracker(":memory:")
    audit_log = AuditLog(":memory:")
    server = _build_server(auth_store, usage_tracker=usage_tracker, audit_log=audit_log)

    try:
        ctx = _context({"x-api-key": issued.raw_key})
        asyncio.run(server.call_tool("add_memory", {"text": "张三在某公司工作"}, context=ctx))
        asyncio.run(server.call_tool("forget_memory", {"query": "张三 任职于 某公司"}, context=ctx))

        assert usage_tracker.event_count(issued.user_id, "add_memory") == 1
        assert len(audit_log.query(issued.user_id)) == 1
    finally:
        _truncate()
