from memory_core.graph.models import Entity, Relation
from memory_core.retrieval.ranker import build_context


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

    assert "张三任职于某公司。" in context
    assert "张三居住在北京。" in context
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
    assert context == "arb。"
