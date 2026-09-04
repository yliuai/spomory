from datetime import UTC, datetime

from memory_core.graph.models import Entity, Relation
from memory_core.retrieval.ranker import build_context


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
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    entities_by_id = {e.id: e for e in [a, b, c]}
    relations = [
        Relation(subject_id=a.id, predicate="r", object_id=b.id),
        Relation(subject_id=a.id, predicate="r", object_id=b.id),  # duplicate
        Relation(subject_id=c.id, predicate="r", object_id=c.id),  # not in top_k
    ]
    context = build_context(relations, entities_by_id, ranked_entity_ids=[a.id, b.id], top_k=2)
    assert context.startswith("arb")
    assert context.count("arb") == 1  # deduped, not appearing twice
