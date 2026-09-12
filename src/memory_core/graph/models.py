"""Core graph data models: entities and relations.

Provenance and timestamp fields are mandatory (not optional extras) because
Epic 7's export format ("记忆护照") requires every fact to be traceable back
to its source and to a point in time — that requirement is designed in here
from the start rather than bolted on later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

MemoryType = Literal["semantic", "episodic", "procedural"]


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Provenance(BaseModel):
    """Where a piece of memory came from, for auditability and export."""

    source_id: str = Field(description="Opaque id of the source document/conversation/etc.")
    source_span: str = Field(description="Verbatim text snippet this fact was derived from")
    extractor: str = Field(default="unknown", description="Name/version of the extraction pipeline")


class Entity(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str
    type: str = Field(description="Entity type, e.g. person / organization / concept / event")
    attributes: dict[str, str] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    memory_type: MemoryType = Field(
        default="semantic", description="For Epic 7 export classification (MIF/PAM-style)"
    )
    provenance: list[Provenance] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Relation(BaseModel):
    id: str = Field(default_factory=_new_id)
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    memory_type: MemoryType = Field(
        default="semantic", description="For Epic 7 export classification (MIF/PAM-style)"
    )
    provenance: list[Provenance] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_retrieved_at: datetime | None = Field(
        default=None,
        description=(
            "Epic 11.4: when this relation was last shown in a search_memory "
            "result, so ranking can passively downweight memories that have "
            "gone a long time without being useful. None until the first hit."
        ),
    )
    mention_count: int = Field(
        default=1,
        ge=1,
        description=(
            "Epic 12.1: how many times this exact fact (same subject/"
            "predicate/object) has been extracted from new input, including "
            "the original write. RuleBasedPolicy/TrainedPolicy bump this "
            "instead of writing a duplicate row when a candidate matches an "
            "existing relation exactly, so ranking can favor facts the user "
            "keeps repeating (Hebbian-style) alongside Epic 11.4's staleness "
            "decay, which only tracks the opposite signal (how long since a "
            "fact was last *retrieved*, not how often it's been *restated*)."
        ),
    )
    valid_from: datetime = Field(
        default_factory=_utcnow,
        description=(
            "Epic 11.7: transaction-time start of *this specific value* -- "
            "when the system started believing subject/predicate/object as "
            "currently written. Unlike `created_at` (fixed at this relation "
            "id's first write and never touched again), `valid_from` moves "
            "forward on every UPDATE, since a corrected fact's *previous* "
            "value stopped being current at that point. This is transaction "
            "time (when the system's belief changed), not real-world valid "
            "time (when the fact actually became true) -- the latter would "
            "need dates extracted from the source text, which this doesn't "
            "attempt; see `GraphStoreBase.relation_as_of`."
        ),
    )
