from datetime import UTC, datetime

import pytest

from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Relation
from memory_core.memory_manager.actions import ActionType, MemoryAction, apply_action


def _store_with_one_relation(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store.add_entities([a, b])
    relation = Relation(subject_id=a.id, predicate="r", object_id=b.id)
    store.add_relations([relation])
    return store, a, b, relation


def test_add_action_writes_relation(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store.add_entities([a, b])
    relation = Relation(subject_id=a.id, predicate="r", object_id=b.id)

    apply_action(MemoryAction(ActionType.ADD, relation=relation), store)

    assert len(store.all_relations()) == 1


def test_update_action_modifies_relation(tmp_path):
    store, _a, _b, relation = _store_with_one_relation(tmp_path)

    apply_action(
        MemoryAction(ActionType.UPDATE, target_id=relation.id, updates={"confidence": 0.42}),
        store,
    )

    updated = next(r for r in store.all_relations() if r.id == relation.id)
    assert updated.confidence == 0.42
    assert len(store.all_relations()) == 1  # upsert, not a duplicate


def test_update_action_refreshes_updated_at_but_not_created_at(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store.add_entities([a, b])
    original_time = datetime(2020, 1, 1, tzinfo=UTC)
    relation = Relation(
        subject_id=a.id, predicate="r", object_id=b.id,
        created_at=original_time, updated_at=original_time,
    )
    store.add_relations([relation])

    apply_action(
        MemoryAction(ActionType.UPDATE, target_id=relation.id, updates={"confidence": 0.9}),
        store,
    )

    updated = next(r for r in store.all_relations() if r.id == relation.id)
    assert updated.created_at == original_time  # when the fact was first recorded
    assert updated.updated_at > original_time  # when it was last changed -- must move


def test_update_action_archives_the_pre_update_value(tmp_path):
    # Epic 11.7: apply_action's UPDATE branch is the one place that should
    # actually create bitemporal history -- verifies the full path (not
    # just the store primitive graph_store_contract.py already covers).
    store, _a, _b, relation = _store_with_one_relation(tmp_path)
    before_update = datetime.now(UTC)

    apply_action(
        MemoryAction(ActionType.UPDATE, target_id=relation.id, updates={"confidence": 0.42}),
        store,
    )

    as_of_before = store.relation_as_of(relation.id, before_update)
    assert as_of_before is not None
    assert as_of_before.confidence == relation.confidence  # the original, pre-update value

    as_of_now = store.relation_as_of(relation.id, datetime.now(UTC))
    assert as_of_now is not None
    assert as_of_now.confidence == 0.42


def test_delete_action_removes_relation_without_touching_entities(tmp_path):
    store, a, b, relation = _store_with_one_relation(tmp_path)

    apply_action(MemoryAction(ActionType.DELETE, target_id=relation.id), store)

    assert store.all_relations() == []
    assert store.get_entity(a.id) is not None
    assert store.get_entity(b.id) is not None


def test_delete_action_removes_entity(tmp_path):
    store, a, _b, _relation = _store_with_one_relation(tmp_path)

    apply_action(MemoryAction(ActionType.DELETE, target_id=a.id), store)

    assert store.get_entity(a.id) is None
    assert store.all_relations() == []  # cascades, per delete_entity's contract


def test_noop_action_is_a_no_op(tmp_path):
    store, _a, _b, _relation = _store_with_one_relation(tmp_path)

    apply_action(MemoryAction(ActionType.NOOP), store)

    assert len(store.all_relations()) == 1


def test_add_without_relation_raises(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    with pytest.raises(ValueError):
        apply_action(MemoryAction(ActionType.ADD), store)
