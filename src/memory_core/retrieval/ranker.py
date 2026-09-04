"""Turn PPR-ranked graph output into a natural-language context block for an LLM prompt."""

from __future__ import annotations

from memory_core.graph.models import Entity, Relation


def _relation_to_sentence(relation: Relation, entities_by_id: dict[str, Entity]) -> str:
    subject = entities_by_id.get(relation.subject_id)
    obj = entities_by_id.get(relation.object_id)
    subject_name = subject.name if subject else relation.subject_id
    object_name = obj.name if obj else relation.object_id
    # created_at answers a different "when" than any date folded into the
    # predicate during extraction (graph/extract.py's date-in-predicate
    # trick captures "when the event happened"; this is "when the system
    # recorded it") -- both are real timestamps on the model, but only the
    # event date was ever making it into rendered context. Without this,
    # "when did I mention X" was unanswerable no matter how good retrieval
    # was, because the information never left the database.
    recorded = relation.created_at.strftime("%Y-%m-%d")
    return f"{subject_name}{relation.predicate}{object_name}（记录于{recorded}）。"


def build_context(
    relations: list[Relation],
    entities_by_id: dict[str, Entity],
    ranked_entity_ids: list[str],
    top_k: int = 20,
) -> str:
    """Render the relations touching the top-``top_k`` ranked entities as prose.

    Relations are ordered by how highly their more-relevant endpoint ranked,
    so the resulting context reads roughly most-to-least relevant.
    """
    rank_position = {entity_id: i for i, entity_id in enumerate(ranked_entity_ids)}
    relevant = [
        r
        for r in relations
        if r.subject_id in rank_position or r.object_id in rank_position
    ]

    def relevance(relation: Relation) -> int:
        # Sum (not min) of both endpoints' ranks: when relations share one
        # highly-ranked endpoint (e.g. all touch the query's anchor entity),
        # this still orders them by how relevant their *other* endpoint is,
        # instead of leaving them all tied.
        return rank_position.get(relation.subject_id, len(rank_position)) + rank_position.get(
            relation.object_id, len(rank_position)
        )

    relevant.sort(key=relevance)
    top_entities = set(ranked_entity_ids[:top_k])
    selected = [
        r for r in relevant if r.subject_id in top_entities or r.object_id in top_entities
    ]

    seen: set[str] = set()
    sentences: list[str] = []
    for relation in selected:
        sentence = _relation_to_sentence(relation, entities_by_id)
        if sentence not in seen:
            seen.add(sentence)
            sentences.append(sentence)

    return "".join(sentences)
