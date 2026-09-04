"""The memory-management action space: ADD / UPDATE / DELETE / NOOP.

Epic 3.5 will swap the caller of these from a rule-based policy to a
GRPO-trained model's output; the actions themselves — and their effect on
the graph store — don't change either way, which is the point of keeping
this module decoupled from whatever decides *which* action to take.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from memory_core.graph.models import Entity, Provenance, Relation
from memory_core.graph.store import GraphStoreBase


class ActionType(str, Enum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    NOOP = "NOOP"


@dataclass
class MemoryAction:
    action_type: ActionType
    # For ADD: a brand-new relation to write.
    # For UPDATE: an existing relation id plus the new field values to apply.
    # For DELETE: an existing entity or relation id to remove.
    # For NOOP: unused.
    relation: Relation | None = None
    target_id: str | None = None
    updates: dict[str, object] | None = None


def apply_action(action: MemoryAction, store: GraphStoreBase) -> None:
    """Execute one memory-management action against the graph store."""
    if action.action_type is ActionType.ADD:
        if action.relation is None:
            raise ValueError("ADD action requires `relation`")
        store.add_relations([action.relation])

    elif action.action_type is ActionType.UPDATE:
        if action.target_id is None or action.updates is None:
            raise ValueError("UPDATE action requires `target_id` and `updates`")
        relation = _find_relation(store, action.target_id)
        # updated_at must actually change on an update, or a stale-but-corrected
        # fact keeps reporting its original creation time forever.
        updates_with_timestamp = {**action.updates, "updated_at": datetime.now(UTC)}
        updated = relation.model_copy(update=updates_with_timestamp)
        store.add_relations([updated])

    elif action.action_type is ActionType.DELETE:
        if action.target_id is None:
            raise ValueError("DELETE action requires `target_id`")
        if store.get_entity(action.target_id) is not None:
            store.delete_entity(action.target_id)
        else:
            store.delete_relation(action.target_id)

    elif action.action_type is ActionType.NOOP:
        pass


def _find_relation(store: GraphStoreBase, relation_id: str) -> Relation:
    for relation in store.all_relations():
        if relation.id == relation_id:
            return relation
    raise KeyError(f"no relation with id {relation_id!r}")


__all__ = ["ActionType", "Entity", "MemoryAction", "Provenance", "apply_action"]
