import asyncio

import pytest

pytest.importorskip("mcp")

from memory_core.graph.local_store import LocalGraphStore  # noqa: E402
from memory_core.mcp_server.server import build_server  # noqa: E402
from tests.test_incremental import FakeLLMProvider  # noqa: E402


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
