"""Shared behavioral contract every `GraphStoreBase` implementation must
satisfy. Subclass `GraphStoreContractTests` and provide a `store` fixture to
run it against a new backend — this is what lets `PostgresGraphStore` claim
interface parity with `LocalGraphStore` even where it can't be exercised
against a real database in this environment (see test_postgres_store.py).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memory_core.graph.models import Entity, Relation


class GraphStoreContractTests:
    @pytest.fixture
    def store(self):
        raise NotImplementedError("subclasses must override the `store` fixture")

    def test_add_and_get_entity(self, store):
        entity = Entity(name="张三", type="person")
        store.add_entities([entity])
        assert store.get_entity(entity.id).name == "张三"
        assert store.get_entity("does-not-exist") is None

    def test_upsert_entity_by_id(self, store):
        entity = Entity(name="a", type="thing")
        store.add_entities([entity])
        updated = entity.model_copy(update={"name": "b"})
        store.add_entities([updated])
        assert store.get_entity(entity.id).name == "b"
        assert len(store.all_entities()) == 1

    def test_upsert_relation_retargeting_an_endpoint(self, store):
        a, old, new = Entity(name="a", type="thing"), Entity(name="old", type="thing"), Entity(
            name="new", type="thing"
        )
        store.add_entities([a, old, new])
        relation = Relation(subject_id=a.id, predicate="r", object_id=old.id)
        store.add_relations([relation])

        retargeted = relation.model_copy(update={"object_id": new.id})
        store.add_relations([retargeted])

        all_relations = store.all_relations()
        assert len(all_relations) == 1  # replaced in place, not appended
        assert all_relations[0].object_id == new.id
        assert store.get_neighbors(old.id) == []  # no stale edge left behind
        assert len(store.get_neighbors(new.id)) == 1

    def test_find_entities_by_name_and_alias(self, store):
        entity = Entity(name="OpenAI", type="organization", aliases=["Open AI"])
        store.add_entities([entity])
        assert store.find_entities_by_name("  openai  ")[0].id == entity.id
        assert store.find_entities_by_name("Open AI")[0].id == entity.id
        assert store.find_entities_by_name("nope") == []

    def test_add_relations_and_get_neighbors(self, store):
        a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
        store.add_entities([a, b])
        relation = Relation(subject_id=a.id, predicate="r", object_id=b.id)
        store.add_relations([relation])

        neighbors = store.get_neighbors(a.id)
        assert len(neighbors) == 1
        assert neighbors[0].id == relation.id
        assert len(store.get_neighbors(b.id)) == 1  # symmetric: subject or object

    def test_query_subgraph_respects_hop_count(self, store):
        a, b, c = (Entity(name=n, type="thing") for n in "abc")
        store.add_entities([a, b, c])
        store.add_relations(
            [
                Relation(subject_id=a.id, predicate="r", object_id=b.id),
                Relation(subject_id=b.id, predicate="r", object_id=c.id),
            ]
        )

        entities, relations = store.query_subgraph([a.id], hops=1)
        assert {e.id for e in entities} == {a.id, b.id}
        assert len(relations) == 1

        entities, relations = store.query_subgraph([a.id], hops=2)
        assert {e.id for e in entities} == {a.id, b.id, c.id}
        assert len(relations) == 2

    def test_delete_entity_cascades_relations(self, store):
        a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
        store.add_entities([a, b])
        store.add_relations([Relation(subject_id=a.id, predicate="r", object_id=b.id)])

        store.delete_entity(a.id)

        assert store.get_entity(a.id) is None
        assert store.get_entity(b.id) is not None
        assert store.all_relations() == []

    def test_delete_relation_leaves_entities(self, store):
        a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
        store.add_entities([a, b])
        relation = Relation(subject_id=a.id, predicate="r", object_id=b.id)
        store.add_relations([relation])

        store.delete_relation(relation.id)

        assert store.all_relations() == []
        assert store.get_entity(a.id) is not None
        assert store.get_entity(b.id) is not None

    def test_all_entities_and_relations(self, store):
        a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
        store.add_entities([a, b])
        store.add_relations([Relation(subject_id=a.id, predicate="r", object_id=b.id)])

        assert len(store.all_entities()) == 2
        assert len(store.all_relations()) == 1

    def test_relation_as_of_reconstructs_a_superseded_value(self, store):
        # Epic 11.7: "recorded wrong info, later corrected" -- querying a
        # transaction-time point before the correction must still return
        # the (wrong, at the time) value the system believed back then,
        # while querying now returns the corrected one.
        a = Entity(name="张三", type="person")
        wrong_employer = Entity(name="公司A", type="organization")
        right_employer = Entity(name="公司B", type="organization")
        store.add_entities([a, wrong_employer, right_employer])

        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        relation = Relation(
            subject_id=a.id, predicate="任职于", object_id=wrong_employer.id, valid_from=t0
        )
        store.add_relations([relation])

        t1 = datetime(2026, 6, 1, tzinfo=UTC)
        store.archive_relation_version(relation, superseded_at=t1)
        corrected = relation.model_copy(update={"object_id": right_employer.id, "valid_from": t1})
        store.add_relations([corrected])

        # Before the correction: the system believed the wrong employer.
        as_of_before = store.relation_as_of(relation.id, datetime(2026, 3, 1, tzinfo=UTC))
        assert as_of_before is not None
        assert as_of_before.object_id == wrong_employer.id

        # After the correction: the current, right value.
        as_of_after = store.relation_as_of(relation.id, datetime(2026, 9, 1, tzinfo=UTC))
        assert as_of_after is not None
        assert as_of_after.object_id == right_employer.id

        # Currently-live query must agree with the "as of now" reading.
        current = next(r for r in store.all_relations() if r.id == relation.id)
        assert current.object_id == right_employer.id

        # Before the fact was ever recorded: nothing to find.
        assert store.relation_as_of(relation.id, datetime(2025, 1, 1, tzinfo=UTC)) is None

    def test_relation_as_of_unknown_id_returns_none(self, store):
        assert store.relation_as_of("does-not-exist", datetime.now(UTC)) is None
