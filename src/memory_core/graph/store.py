"""Storage adapter abstraction.

Frozen early and deliberately: per the business plan's layered open-source
strategy, the storage/backend adapter layer is the one piece meant to be
implemented by third parties later (Phase 2), while the retrieval and
memory-management logic on top of it stays closed. That means this
interface has to be stable from day one, not iterated on casually.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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
    def all_entities(self) -> list[Entity]:
        raise NotImplementedError

    @abstractmethod
    def all_relations(self) -> list[Relation]:
        raise NotImplementedError
