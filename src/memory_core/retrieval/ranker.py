"""Turn PPR-ranked graph output into a natural-language context block for an LLM prompt."""

from __future__ import annotations

from datetime import UTC, datetime

from memory_core.graph.models import Entity, Relation

# Epic 11.4: passive complement to the RL memory manager's active ADD/UPDATE/
# DELETE/NOOP decisions, which have no notion of "hasn't been useful in
# months, quietly rank it lower." Chosen so a relation unretrieved for this
# long picks up a full extra rank-position's worth of penalty -- noticeable
# but not enough to bury a memory that's still clearly more relevant.
_STALENESS_HALF_LIFE_DAYS = 30.0


def _staleness_penalty(relation: Relation, now: datetime) -> float:
    """Days since `relation` was last shown in a search result, scaled by
    the half-life above. Falls back to `created_at` when `last_retrieved_at`
    is still `None` (never yet retrieved) so a brand-new fact isn't treated
    as maximally stale just because it hasn't had a chance to be queried."""
    reference = relation.last_retrieved_at or relation.created_at
    days_stale = max((now - reference).total_seconds() / 86400, 0.0)
    return days_stale / _STALENESS_HALF_LIFE_DAYS


def relation_relevance_score(
    relation: Relation, rank_position: dict[str, int], now: datetime | None = None
) -> float:
    """Lower is more relevant. Combines the PPR-derived rank of both
    endpoints (sum, not min: when relations share one highly-ranked
    endpoint, this still orders them by how relevant their *other* endpoint
    is, instead of leaving them all tied) with Epic 11.4's staleness
    penalty, so two relations tied on rank are broken by which one has
    actually been useful more recently.
    """
    base = rank_position.get(relation.subject_id, len(rank_position)) + rank_position.get(
        relation.object_id, len(rank_position)
    )
    return base + _staleness_penalty(relation, now or datetime.now(UTC))


def select_relevant_relations(
    relations: list[Relation],
    entities_by_id: dict[str, Entity],
    ranked_entity_ids: list[str],
    top_k: int = 20,
    now: datetime | None = None,
) -> list[Relation]:
    """The subset of `relations` `build_context` would render, in the same
    order -- factored out so a caller (e.g. `search_memory`) can record which
    relations were actually shown a memory-retrieval hit without
    re-deriving this selection by hand."""
    rank_position = {entity_id: i for i, entity_id in enumerate(ranked_entity_ids)}
    relevant = [
        r
        for r in relations
        if r.subject_id in rank_position or r.object_id in rank_position
    ]

    now = now or datetime.now(UTC)
    relevant.sort(key=lambda r: relation_relevance_score(r, rank_position, now))
    top_entities = set(ranked_entity_ids[:top_k])
    return [r for r in relevant if r.subject_id in top_entities or r.object_id in top_entities]

_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x3000, 0x303F),  # CJK punctuation
    (0xFF00, 0xFFEF),  # halfwidth/fullwidth forms (e.g. full-width punctuation)
)


def _is_cjk_text(text: str) -> bool:
    """Whether ``text`` reads as CJK, to decide how a sentence should be assembled.

    Chinese (and Japanese/Korean) text conventionally has no spaces between
    words, so joining subject+predicate+object directly is correct for it.
    Space-delimited languages (English and most others) need spaces at
    those joins or the sentence reads as one run-on word -- there's no
    language field on Relation/Entity to consult, so this looks at the
    actual characters instead.
    """
    return any(
        any(start <= ord(ch) <= end for start, end in _CJK_RANGES) for ch in text
    )


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
    #
    # created_at is stored in UTC (models.py's _utcnow()); .astimezone()
    # with no argument converts to the local system timezone before
    # formatting, so what's shown matches the clock the user actually reads
    # -- rendering the raw UTC value would be off by a fixed offset (e.g. 8
    # hours for a China-local deployment) from what "when did I say this"
    # intuitively expects.
    recorded = relation.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")

    if _is_cjk_text(f"{subject_name}{relation.predicate}{object_name}"):
        return f"{subject_name}{relation.predicate}{object_name}（记录于{recorded}）。"
    return f"{subject_name} {relation.predicate} {object_name} (recorded at {recorded})."


def build_context(
    relations: list[Relation],
    entities_by_id: dict[str, Entity],
    ranked_entity_ids: list[str],
    top_k: int = 20,
) -> str:
    """Render the relations touching the top-``top_k`` ranked entities as prose.

    Relations are ordered by how highly their more-relevant endpoint ranked
    (Epic 11.4: with ties broken by staleness -- see `select_relevant_relations`),
    so the resulting context reads roughly most-to-least relevant.
    """
    selected = select_relevant_relations(relations, entities_by_id, ranked_entity_ids, top_k)

    seen: set[str] = set()
    sentences: list[str] = []
    for relation in selected:
        sentence = _relation_to_sentence(relation, entities_by_id)
        if sentence not in seen:
            seen.add(sentence)
            sentences.append(sentence)

    return "".join(sentences)
