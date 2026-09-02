"""Full export and true-delete: the technical backing for the "记忆护照"
promise — export the whole graph, or physically erase it, on demand.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory_core.graph.store import GraphStoreBase

from .schema import ExportedEntity, ExportedRelation, MemoryExport


def export_all(store: GraphStoreBase, subject_id: str) -> MemoryExport:
    entities = [ExportedEntity.from_entity(e) for e in store.all_entities()]
    relations = [ExportedRelation.from_relation(r) for r in store.all_relations()]
    return MemoryExport(subject_id=subject_id, entities=entities, relations=relations)


@dataclass
class DeletionReceipt:
    """A verifiable confirmation that data was physically removed, not just hidden."""

    subject_id: str
    entities_deleted: int
    relations_deleted: int
    entities_remaining: int
    relations_remaining: int

    @property
    def fully_deleted(self) -> bool:
        return self.entities_remaining == 0 and self.relations_remaining == 0


def delete_all(store: GraphStoreBase, subject_id: str) -> DeletionReceipt:
    """Physically delete every entity (and, transitively, every relation touching one)."""
    entities_before = store.all_entities()
    relations_before = len(store.all_relations())

    for entity in entities_before:
        store.delete_entity(entity.id)

    remaining_entities = store.all_entities()
    remaining_relations = store.all_relations()

    return DeletionReceipt(
        subject_id=subject_id,
        entities_deleted=len(entities_before) - len(remaining_entities),
        relations_deleted=relations_before - len(remaining_relations),
        entities_remaining=len(remaining_entities),
        relations_remaining=len(remaining_relations),
    )
