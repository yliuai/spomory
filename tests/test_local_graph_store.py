import random

from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Relation


def _make_graph(n_entities: int, n_relations: int) -> tuple[list[Entity], list[Relation]]:
    entities = [Entity(name=f"entity-{i}", type="thing") for i in range(n_entities)]
    rng = random.Random(0)
    relations = [
        Relation(
            subject_id=rng.choice(entities).id,
            predicate="related_to",
            object_id=rng.choice(entities).id,
        )
        for _ in range(n_relations)
    ]
    return entities, relations


def test_create_query_persist_across_restart(tmp_path):
    db_path = tmp_path / "graph.sqlite3"
    entities, relations = _make_graph(100, 200)

    store = LocalGraphStore(db_path)
    store.add_entities(entities)
    store.add_relations(relations)

    assert len(store.all_entities()) == 100
    assert len(store.all_relations()) == 200

    sample = entities[0]
    assert store.get_entity(sample.id).name == sample.name
    assert store.find_entities_by_name(sample.name)[0].id == sample.id

    # simulate a process restart: drop the in-memory store, reopen from disk
    del store
    reopened = LocalGraphStore(db_path)
    assert len(reopened.all_entities()) == 100
    assert len(reopened.all_relations()) == 200
    assert reopened.get_entity(sample.id).name == sample.name


def test_query_subgraph_and_delete(tmp_path):
    store = LocalGraphStore(tmp_path / "graph.sqlite3")
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    store.add_entities([a, b, c])
    store.add_relations(
        [
            Relation(subject_id=a.id, predicate="knows", object_id=b.id),
            Relation(subject_id=b.id, predicate="knows", object_id=c.id),
        ]
    )

    sub_entities, sub_relations = store.query_subgraph([a.id], hops=1)
    ids = {e.id for e in sub_entities}
    assert ids == {a.id, b.id}
    assert len(sub_relations) == 1


def test_delete_relation_leaves_entities_intact(tmp_path):
    store = LocalGraphStore(tmp_path / "graph.sqlite3")
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store.add_entities([a, b])
    relation = Relation(subject_id=a.id, predicate="knows", object_id=b.id)
    store.add_relations([relation])

    store.delete_relation(relation.id)

    assert store.all_relations() == []
    assert store.get_entity(a.id) is not None
    assert store.get_entity(b.id) is not None

    store.delete_entity(b.id)
    assert store.get_entity(b.id) is None
    assert all(r.subject_id != b.id and r.object_id != b.id for r in store.all_relations())
