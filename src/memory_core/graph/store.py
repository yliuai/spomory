"""Storage adapter abstraction.

Frozen early and deliberately: per the business plan's layered open-source
strategy, the storage/backend adapter layer is the one piece meant to be
implemented by third parties later (Phase 2), while the retrieval and
memory-management logic on top of it stays closed. That means this
interface has to be stable from day one, not iterated on casually.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .models import Entity, Relation


class GraphStoreBase(ABC):
    """Abstract interface every graph storage backend must implement."""

    @abstractmethod
    def add_entities(self, entities: list[Entity]) -> None:
        """Insert or upsert (by id) a batch of entities."""
        raise NotImplementedError

    @abstractmethod
    def add_relations(self, relations: list[Relation]) -> None:
        """Insert or upsert (by id) a batch of relations."""
        raise NotImplementedError

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None:
        raise NotImplementedError

    @abstractmethod
    def find_entities_by_name(self, name: str) -> list[Entity]:
        """Exact/alias name lookup, used for entity resolution during merge."""
        raise NotImplementedError

    @abstractmethod
    def get_neighbors(self, entity_id: str) -> list[Relation]:
        """All relations where ``entity_id`` is the subject or the object."""
        raise NotImplementedError

    @abstractmethod
    def query_subgraph(self, entity_ids: list[str], hops: int = 1) -> tuple[list[Entity], list[Relation]]:
        """Return the induced subgraph reachable within ``hops`` steps of ``entity_ids``."""
        raise NotImplementedError

    @abstractmethod
    def delete_entity(self, entity_id: str) -> None:
        """Physically remove an entity and any relations touching it (Epic 7 "真删除")."""
        raise NotImplementedError

    @abstractmethod
    def delete_relation(self, relation_id: str) -> None:
        """Physically remove a single relation without touching its endpoints."""
        raise NotImplementedError

    @abstractmethod
    def all_entities(self) -> list[Entity]:
        raise NotImplementedError

    @abstractmethod
    def all_relations(self) -> list[Relation]:
        raise NotImplementedError

    @abstractmethod
    def archive_relation_version(self, old_relation: Relation, superseded_at: datetime) -> None:
        """Epic 11.7: record `old_relation` -- a relation's content the
        instant before an UPDATE overwrites it -- into transaction-time
        history, so `relation_as_of` can still answer "what did the system
        believe at some point in the past" after a correction. Called by
        `memory_manager.actions.apply_action`'s UPDATE branch, which is the
        only place that legitimately treats an upsert as "this fact
        changed" rather than a fresh write or a data-migration replay (see
        that module for why archiving doesn't live inside `add_relations`
        itself)."""
        raise NotImplementedError

    @abstractmethod
    def relation_as_of(self, relation_id: str, as_of: datetime) -> Relation | None:
        """Epic 11.7: the value `relation_id` held at transaction-time
        `as_of` -- the current row if `as_of` is on or after its
        `valid_from`, otherwise whichever archived version's
        `[valid_from, valid_to)` window contains `as_of`. Returns `None` if
        `relation_id` didn't exist yet at that point (or doesn't exist at
        all). This answers "what did the system believe was true then", not
        "when did this become true in the real world" -- see `Relation
        .valid_from`'s docstring for that distinction."""
        raise NotImplementedError
