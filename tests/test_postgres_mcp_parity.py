"""Epic 8.2's functional-parity check: the same add_memory/search_memory
round trip verified against LocalGraphStore in test_mcp_server.py, run here
against PostgresGraphStore instead — swapping the backend shouldn't change
tool behavior. Skipped without DATABASE_URL, same as test_postgres_store.py.
"""

import asyncio
import os

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("mcp")

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set DATABASE_URL to a real Postgres instance to run this"
)


def test_add_then_search_round_trips_through_postgres_backend():
    from memory_core.graph.postgres_store import PostgresGraphStore
    from memory_core.llm.base import TripleCandidate
    from memory_core.mcp_server.server import build_server
    from tests.test_incremental import FakeLLMProvider
    from tests.test_mcp_server import FakeEmbeddingProvider

    store = PostgresGraphStore(DATABASE_URL)
    store._conn.execute("TRUNCATE entities, relations")

    llm = FakeLLMProvider(
        [TripleCandidate(subject="张三", predicate="任职于", object="某公司", source_span="s")]
    )
    server = build_server(store, llm, FakeEmbeddingProvider())

    add_result = asyncio.run(server.call_tool("add_memory", {"text": "张三在某公司工作"}))
    assert "新增实体 2 个" in str(add_result)

    search_result = asyncio.run(server.call_tool("search_memory", {"query": "张三"}))
    assert "张三任职于某公司" in str(search_result)

    store._conn.execute("TRUNCATE entities, relations")
