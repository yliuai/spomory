import asyncio

import pytest

pytest.importorskip("mcp")

from memory_core.graph.local_store import LocalGraphStore
from memory_core.mcp_server.server import build_server
from memory_core.usage import UsageTracker
from tests.test_incremental import FakeLLMProvider


class FakeEmbeddingProvider:
    def embed(self, texts):
        import numpy as np

        # Deterministic, content-independent embedding: good enough to prove
        # the tool wiring works without pulling in a real model here.
        return np.array([[hash(t) % 997, 1.0] for t in texts], dtype=float)


def test_all_four_tools_are_registered():
    store = LocalGraphStore(":memory:")
    server = build_server(store, FakeLLMProvider([]), FakeEmbeddingProvider())

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"add_memory", "search_memory", "get_graph", "export_memory"}


def test_add_memory_records_usage_when_tracker_given():
    store = LocalGraphStore(":memory:")
    from memory_core.llm.base import TripleCandidate

    llm = FakeLLMProvider(
        [TripleCandidate(subject="张三", predicate="任职于", object="某公司", source_span="s")]
    )
    tracker = UsageTracker(":memory:")
    server = build_server(store, llm, FakeEmbeddingProvider(), usage_tracker=tracker, user_id="u1")

    asyncio.run(server.call_tool("add_memory", {"text": "张三在某公司工作"}))

    assert tracker.event_count("u1", "add_memory") == 1
    assert tracker.active_users_since(7) == 1
