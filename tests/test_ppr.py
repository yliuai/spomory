from memory_core.graph.models import Entity, Relation
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities


def _entity(name: str) -> Entity:
    return Entity(name=name, type="thing")


def test_ppr_recalls_three_hop_path_above_unrelated_nodes():
    # Path: seed -> a -> b -> c  (3 hops away from the seed)
    seed, a, b, c = (_entity(n) for n in ["seed", "a", "b", "c"])
    path_entities = [seed, a, b, c]
    path_relations = [
        Relation(subject_id=seed.id, predicate="r", object_id=a.id),
        Relation(subject_id=a.id, predicate="r", object_id=b.id),
        Relation(subject_id=b.id, predicate="r", object_id=c.id),
    ]

    # 20+ unrelated nodes forming their own disconnected cluster
    unrelated = [_entity(f"u{i}") for i in range(24)]
    unrelated_relations = [
        Relation(subject_id=unrelated[i].id, predicate="r", object_id=unrelated[i + 1].id)
        for i in range(len(unrelated) - 1)
    ]

    entities = path_entities + unrelated
    relations = path_relations + unrelated_relations

    scores = personalized_pagerank(entities, relations, seed_entity_ids=[seed.id])
    ranked = rank_entities(scores)
    ranked_ids = [entity_id for entity_id, _ in ranked]

    path_ids = {seed.id, a.id, b.id, c.id}
    top_4 = set(ranked_ids[:4])
    assert top_4 == path_ids

    # every unrelated node ranks below every path node
    max_unrelated_score = max(scores[u.id] for u in unrelated)
    min_path_score = min(scores[i] for i in path_ids)
    assert min_path_score > max_unrelated_score


def test_ppr_handles_no_valid_seeds():
    entities = [_entity("a"), _entity("b")]
    relations = [Relation(subject_id=entities[0].id, predicate="r", object_id=entities[1].id)]
    scores = personalized_pagerank(entities, relations, seed_entity_ids=["missing"])
    assert set(scores.keys()) == {e.id for e in entities}
    assert all(v == 0.0 for v in scores.values())
