"""PH.md's unauthenticated, ephemeral extraction+retrieval endpoint: lets a
website visitor see what add_memory/search_memory actually do without
registering. Deliberately stateless -- runs the same extraction/retrieval
pipeline real users get, but nothing is written to any store; the request
and response only ever exist for the duration of one call.
"""

from __future__ import annotations

from memory_core.graph.models import Entity, Relation
from memory_core.llm.base import LLMProvider
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
from memory_core.retrieval.query_match import match_query_to_triples
from memory_core.retrieval.ranker import build_context

# Bounds the LLM extraction call's cost -- this endpoint has no account
# behind it to hold accountable for a runaway bill, only the IP rate limit
# in auth.py, so the per-call cost itself needs a ceiling too.
MAX_DEMO_TEXT_LENGTH = 2000

DEMO_SEARCH_TOP_K = 10


class DemoTextTooLongError(ValueError):
    pass


def extract_and_search(
    llm: LLMProvider, embedder, text: str, query: str | None
) -> dict[str, object]:
    """Runs one-shot extraction (and, if `query` is given, retrieval) over
    `text` alone -- no existing graph, no persistence. Entity resolution is
    simpler than `IncrementalIngestor`'s: exact-name matching within this
    one call is enough, since there's no prior graph to merge against."""
    if len(text) > MAX_DEMO_TEXT_LENGTH:
        raise DemoTextTooLongError(f"text must be at most {MAX_DEMO_TEXT_LENGTH} characters")

    candidates = llm.extract_triples(text)

    entities_by_name: dict[str, Entity] = {}

    def resolve(name: str) -> str:
        if name not in entities_by_name:
            entities_by_name[name] = Entity(name=name, type="unknown")
        return entities_by_name[name].id

    relations = [
        Relation(subject_id=resolve(c.subject), predicate=c.predicate, object_id=resolve(c.object))
        for c in candidates
    ]
    entities = list(entities_by_name.values())
    entities_by_id = {e.id: e for e in entities}

    result: dict[str, object] = {
        "entities": [{"id": e.id, "name": e.name, "type": e.type} for e in entities],
        "relations": [
            {"id": r.id, "subject_id": r.subject_id, "predicate": r.predicate, "object_id": r.object_id}
            for r in relations
        ],
    }

    if query is not None:
        if not relations:
            result["context"] = ""
        else:
            matches = match_query_to_triples(query, relations, entities_by_id, embedder, top_k=DEMO_SEARCH_TOP_K)
            seed_ids = {m.relation.subject_id for m in matches} | {m.relation.object_id for m in matches}
            scores = personalized_pagerank(entities, relations, seed_entity_ids=list(seed_ids))
            ranked_ids = [entity_id for entity_id, _ in rank_entities(scores)]
            result["context"] = build_context(relations, entities_by_id, ranked_ids, top_k=DEMO_SEARCH_TOP_K) or ""

    return result
