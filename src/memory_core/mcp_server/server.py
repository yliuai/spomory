"""MCP Server exposing the memory graph to any MCP client (Claude Desktop, Cursor, ...).

This is the open-core developer distribution surface described in the
business plan's cold-start playbook: a real, locally-runnable tool people
can install today, backed by whatever ``GraphStoreBase`` implementation is
configured (local by default, cloud once Epic 8.2 lands).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from memory_core.export.exporter import export_all
from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.store import GraphStoreBase
from memory_core.llm.base import LLMProvider
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
from memory_core.retrieval.query_match import match_query_to_triples
from memory_core.retrieval.ranker import build_context


def build_server(store: GraphStoreBase, llm: LLMProvider, embedder) -> FastMCP:
    """Wire the four memory tools up against a given store/llm/embedder.

    Kept as a factory function (rather than module-level globals) so tests
    can inject fakes and so Epic 8.2's cloud backend swap is a one-line change
    at the call site, not a rewrite of this module.
    """
    mcp = FastMCP("memory-core")
    ingestor = IncrementalIngestor(store, llm)

    @mcp.tool()
    def add_memory(text: str, source_id: str = "mcp-session") -> str:
        """Extract facts from `text` and write them into the memory graph."""
        result = ingestor.ingest(text, source_id=source_id)
        return (
            f"新增实体 {result.new_entities} 个，合并已有实体 {result.merged_entities} 个，"
            f"新增关系 {result.new_relations} 条"
        )

    @mcp.tool()
    def search_memory(query: str, top_k: int = 10) -> str:
        """Retrieve and assemble a natural-language context relevant to `query`."""
        entities = store.all_entities()
        relations = store.all_relations()
        entities_by_id = {e.id: e for e in entities}

        matches = match_query_to_triples(query, relations, entities_by_id, embedder, top_k=top_k)
        seed_ids = {r.relation.subject_id for r in matches} | {r.relation.object_id for r in matches}
        scores = personalized_pagerank(entities, relations, seed_entity_ids=list(seed_ids))
        ranked_ids = [entity_id for entity_id, _ in rank_entities(scores)]

        context = build_context(relations, entities_by_id, ranked_ids, top_k=top_k)
        return context or "没有找到相关记忆。"

    @mcp.tool()
    def get_graph(entity_name: str, hops: int = 1) -> str:
        """Return the subgraph around `entity_name` as JSON."""
        matches = store.find_entities_by_name(entity_name)
        if not matches:
            return "{}"
        entity_ids = [e.id for e in matches]
        entities, relations = store.query_subgraph(entity_ids, hops=hops)
        return _subgraph_to_json(entities, relations)

    @mcp.tool()
    def export_memory(subject_id: str = "default") -> str:
        """Export the full memory graph as a JSON memory passport."""
        return export_all(store, subject_id=subject_id).model_dump_json(by_alias=True)

    return mcp


def _subgraph_to_json(entities, relations) -> str:
    import json

    return json.dumps(
        {
            "entities": [e.model_dump(mode="json") for e in entities],
            "relations": [r.model_dump(mode="json") for r in relations],
        },
        ensure_ascii=False,
    )


def default_server() -> FastMCP:
    """Build a server using the default local backend and env-configured providers."""
    from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
    from memory_core.llm.openai_compatible import OpenAICompatibleProvider

    store = LocalGraphStore("memory_core.sqlite3")
    llm = OpenAICompatibleProvider()
    embedder = SentenceTransformerProvider()
    return build_server(store, llm, embedder)
