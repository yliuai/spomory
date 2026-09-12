from datetime import UTC, datetime, timedelta

from memory_core.graph.models import Entity, Relation
from memory_core.retrieval.ranker import (
    build_context,
    relation_relevance_score,
    select_relevant_relations,
)


def test_build_context_surfaces_created_at_so_when_questions_are_answerable():
    """Regression test for a real user-reported gap: search_memory's context
    dropped Relation.created_at entirely, so even though every fact is
    timestamped in the graph, there was no way for the LLM to answer
    "when did I mention X" -- the timestamp never left the database.

    Also covers the follow-up report that the rendered timestamp was
    missing hour/minute/second granularity (date-only). Computes the
    expected local-time string the same way the implementation does
    (created_at is stored in UTC; .astimezone() converts for display)
    rather than hardcoding a date, so this isn't tied to the machine's
    timezone.
    """
    a, b = Entity(name="用户", type="person"), Entity(name="某公司", type="organization")
    entities_by_id = {a.id: a, b.id: b}
    fixed_time = datetime(2026, 3, 14, 12, 34, 56, tzinfo=UTC)
    relation = Relation(
        subject_id=a.id, predicate="在", object_id=b.id, created_at=fixed_time
    )

    context = build_context([relation], entities_by_id, [a.id, b.id], top_k=2)

    expected = fixed_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert expected in context


def test_build_context_spaces_english_sentences_instead_of_running_words_together():
    """Regression test for a real gap found while writing the English README:
    the sentence template was written assuming CJK text (no spaces between
    words is normal there), so English relations rendered as an unreadable
    run-on like "Idoes AI research atCAS" with a Chinese timestamp label
    tacked on regardless of the input language.
    """
    a, b = Entity(name="I", type="person"), Entity(name="CAS", type="organization")
    entities_by_id = {a.id: a, b.id: b}
    fixed_time = datetime(2026, 3, 14, 12, 34, 56, tzinfo=UTC)
    relation = Relation(
        subject_id=a.id, predicate="does AI research at", object_id=b.id, created_at=fixed_time
    )

    context = build_context([relation], entities_by_id, [a.id, b.id], top_k=2)

    expected_time = fixed_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert context == f"I does AI research at CAS (recorded at {expected_time})."


def test_build_context_produces_readable_sentences_in_relevance_order():
    zhangsan = Entity(name="张三", type="person")
    company = Entity(name="某公司", type="organization")
    beijing = Entity(name="北京", type="place")
    entities_by_id = {e.id: e for e in [zhangsan, company, beijing]}

    relations = [
        Relation(subject_id=zhangsan.id, predicate="居住在", object_id=beijing.id),
        Relation(subject_id=zhangsan.id, predicate="任职于", object_id=company.id),
    ]

    ranked_ids = [zhangsan.id, company.id, beijing.id]
    context = build_context(relations, entities_by_id, ranked_ids, top_k=20)

    assert "张三任职于某公司" in context
    assert "张三居住在北京" in context
    assert "（记录于" in context  # created_at surfaces so "when did I say X" is answerable
    # higher-ranked relation (touches company, rank 1) comes before the one
    # touching beijing (rank 2)
    assert context.index("任职于") < context.index("居住在")


def test_build_context_dedupes_and_ignores_out_of_scope_relations():
    # Uses CJK names so the no-space concatenation assertion below tests
    # dedup/scoping specifically, independent of the language-dependent
    # spacing covered by the two tests above.
    a, b, c = (Entity(name=n, type="thing") for n in "甲乙丙")
    entities_by_id = {e.id: e for e in [a, b, c]}
    relations = [
        Relation(subject_id=a.id, predicate="连", object_id=b.id),
        Relation(subject_id=a.id, predicate="连", object_id=b.id),  # duplicate
        Relation(subject_id=c.id, predicate="连", object_id=c.id),  # not in top_k
    ]
    context = build_context(relations, entities_by_id, ranked_entity_ids=[a.id, b.id], top_k=2)
    assert context.startswith("甲连乙")
    assert context.count("甲连乙") == 1  # deduped, not appearing twice


def test_relation_relevance_score_penalizes_long_unretrieved_relations():
    """Epic 11.4: a passive decay signal alongside the RL memory manager's
    active ADD/UPDATE/DELETE/NOOP decisions, which have no notion of "this
    hasn't been useful in months, quietly rank it lower." Two relations tied
    on PPR rank should score differently once one of them has gone a long
    time without a retrieval hit."""
    a, b = Entity(name="甲", type="thing"), Entity(name="乙", type="thing")
    now = datetime(2026, 6, 1, tzinfo=UTC)
    rank_position = {a.id: 0, b.id: 0}  # tied rank -- only staleness should differ

    fresh = Relation(
        subject_id=a.id, predicate="连", object_id=b.id, last_retrieved_at=now - timedelta(days=1)
    )
    stale = Relation(
        subject_id=a.id,
        predicate="连",
        object_id=b.id,
        last_retrieved_at=now - timedelta(days=365),
    )
    never_hit_but_new = Relation(
        subject_id=a.id, predicate="连", object_id=b.id, created_at=now - timedelta(days=1)
    )

    fresh_score = relation_relevance_score(fresh, rank_position, now=now)
    stale_score = relation_relevance_score(stale, rank_position, now=now)
    new_score = relation_relevance_score(never_hit_but_new, rank_position, now=now)

    assert fresh_score < stale_score  # observable drop in relevance for the stale one
    assert new_score < stale_score  # never-yet-queried isn't treated as maximally stale


def test_relation_relevance_score_favors_frequently_restated_facts():
    """Epic 12.1: two relations tied on both PPR rank and staleness should
    score differently once one of them has been restated (mention_count)
    more than the other -- the Hebbian-style complement to Epic 11.4's
    staleness penalty, which only tracks retrieval recency."""
    a, b = Entity(name="甲", type="thing"), Entity(name="乙", type="thing")
    now = datetime(2026, 6, 1, tzinfo=UTC)
    rank_position = {a.id: 0, b.id: 0}

    mentioned_once = Relation(subject_id=a.id, predicate="连", object_id=b.id)
    mentioned_often = Relation(
        subject_id=a.id, predicate="连", object_id=b.id, mention_count=5
    )

    once_score = relation_relevance_score(mentioned_once, rank_position, now=now)
    often_score = relation_relevance_score(mentioned_often, rank_position, now=now)

    assert often_score < once_score  # restated more often -> ranked more relevant


def test_select_relevant_relations_ranks_recently_hit_memory_above_long_stale_one():
    a, b = Entity(name="甲", type="thing"), Entity(name="乙", type="thing")
    entities_by_id = {a.id: a, b.id: b}
    now = datetime(2026, 6, 1, tzinfo=UTC)

    recent = Relation(
        subject_id=a.id, predicate="记得A", object_id=b.id, last_retrieved_at=now - timedelta(days=1)
    )
    stale = Relation(
        subject_id=a.id,
        predicate="记得B",
        object_id=b.id,
        last_retrieved_at=now - timedelta(days=400),
    )

    # Both relations connect the same (a, b) pair, so they're tied on PPR
    # rank -- only the staleness signal should decide their order.
    selected = select_relevant_relations(
        [stale, recent], entities_by_id, ranked_entity_ids=[a.id, b.id], top_k=2, now=now
    )

    assert selected == [recent, stale]
