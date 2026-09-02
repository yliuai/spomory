"""The "记忆护照" (memory passport) export schema.

Design follows the MIF/PAM early-draft conventions cited in the business
plan: semantic/episodic/procedural memory classification, W3C PROV-O-style
provenance (not the full spec, just its shape — source, derivation span,
extractor), and a JSON-LD-flavored top-level ``@context``/``@type`` so the
file is self-describing without inventing a private format from scratch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from memory_core.graph.models import Entity, Relation

JSONLD_CONTEXT: dict[str, Any] = {
    "@vocab": "https://schema.org/",
    "memory": "https://memory-core.dev/schema/memory#",
    "prov": "http://www.w3.org/ns/prov#",
}


class ExportedEntity(BaseModel):
    """An entity as it appears in an export file — same fields as ``Entity``,
    kept as a distinct model so the export format can evolve independently
    of the internal storage model."""

    id: str
    name: str
    type: str
    memory_type: str
    attributes: dict[str, str]
    aliases: list[str]
    provenance: list[dict[str, str]]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: Entity) -> ExportedEntity:
        return cls(
            id=entity.id,
            name=entity.name,
            type=entity.type,
            memory_type=entity.memory_type,
            attributes=entity.attributes,
            aliases=entity.aliases,
            provenance=[p.model_dump() for p in entity.provenance],
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


class ExportedRelation(BaseModel):
    id: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float
    memory_type: str
    provenance: list[dict[str, str]]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_relation(cls, relation: Relation) -> ExportedRelation:
        return cls(
            id=relation.id,
            subject_id=relation.subject_id,
            predicate=relation.predicate,
            object_id=relation.object_id,
            confidence=relation.confidence,
            memory_type=relation.memory_type,
            provenance=[p.model_dump() for p in relation.provenance],
            created_at=relation.created_at,
            updated_at=relation.updated_at,
        )


class MemoryExport(BaseModel):
    context: dict[str, Any] = Field(default=JSONLD_CONTEXT, alias="@context")
    type: str = Field(default="memory:MemoryPassport", alias="@type")
    exported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    subject_id: str
    entities: list[ExportedEntity]
    relations: list[ExportedRelation]

    model_config = {"populate_by_name": True}
