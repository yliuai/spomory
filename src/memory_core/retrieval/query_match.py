"""Query -> triple matching (HippoRAG 2 style: match to triples, not just entity nodes).

Matching against the natural-language rendering of whole triples (rather
than only entity names) is what lets a query like "我上次和某客户聊的报价单里，
提到他家孩子的事了吗" recall the right relation even when no single entity name
in the query exactly matches a node label.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from memory_core.graph.models import Entity, Relation
from memory_core.llm.embedding_base import EmbeddingProvider


@dataclass
class TripleMatch:
    relation: Relation
    score: float


def _triple_text(relation: Relation, entities_by_id: dict[str, Entity]) -> str:
    subject = entities_by_id.get(relation.subject_id)
    obj = entities_by_id.get(relation.object_id)
    subject_name = subject.name if subject else relation.subject_id
    object_name = obj.name if obj else relation.object_id
    return f"{subject_name} {relation.predicate} {object_name}"


def match_query_to_triples(
    query: str,
    relations: list[Relation],
    entities_by_id: dict[str, Entity],
    embedder: EmbeddingProvider,
    top_k: int = 10,
) -> list[TripleMatch]:
    """Rank ``relations`` by embedding similarity between the query and each triple's text."""
    if not relations:
        return []

    texts = [_triple_text(r, entities_by_id) for r in relations]
    vectors = embedder.embed([query, *texts])
    query_vec, triple_vecs = vectors[0], vectors[1:]

    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
    triple_norms = triple_vecs / (
        np.linalg.norm(triple_vecs, axis=1, keepdims=True) + 1e-12
    )
    scores = triple_norms @ query_norm

    ranked = sorted(zip(relations, scores), key=lambda item: item[1], reverse=True)
    return [TripleMatch(relation=r, score=float(s)) for r, s in ranked[:top_k]]
