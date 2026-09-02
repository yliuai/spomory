"""Personalized PageRank diffusion over the memory graph.

Takes seed nodes (from query_match.py's triple matches) and spreads
activation across the graph in a single pass — the HippoRAG-style
alternative to iterative multi-hop RAG. Built on ``networkx.pagerank``
with a personalization vector rather than a hand-rolled PPR
implementation, per TASKS.md's explicit "don't reinvent this" guidance.
"""

from __future__ import annotations

import networkx as nx

from memory_core.graph.models import Entity, Relation


def personalized_pagerank(
    entities: list[Entity],
    relations: list[Relation],
    seed_entity_ids: list[str],
    alpha: float = 0.85,
) -> dict[str, float]:
    """Return every entity id's PPR score, seeded uniformly on ``seed_entity_ids``."""
    graph = nx.Graph()
    graph.add_nodes_from(e.id for e in entities)
    graph.add_edges_from((r.subject_id, r.object_id) for r in relations)

    seeds = [s for s in seed_entity_ids if s in graph]
    if not seeds:
        return dict.fromkeys(graph.nodes, 0.0)

    personalization = {node: (1.0 if node in seeds else 0.0) for node in graph.nodes}
    return nx.pagerank(graph, alpha=alpha, personalization=personalization)


def rank_entities(scores: dict[str, float], top_k: int | None = None) -> list[tuple[str, float]]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[:top_k] if top_k else ranked
