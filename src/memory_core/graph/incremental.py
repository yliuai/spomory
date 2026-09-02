"""Incremental write/merge logic.

Only the newly-extracted triples are touched on each call — there is no
step here that re-reads or re-derives the rest of the graph, which is the
property that makes this "incremental" rather than an indexer that
rebuilds everything (the LightRAG-style design choice called out in the
business plan, as opposed to GraphRAG's full-rebuild-per-update approach).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from memory_core.llm.base import LLMProvider

from .models import Entity, Provenance, Relation
from .store import GraphStoreBase


@dataclass
class IngestResult:
    new_entities: int = 0
    merged_entities: int = 0
    new_relations: int = 0
    entity_ids_by_name: dict[str, str] = field(default_factory=dict)


class IncrementalIngestor:
    """Extracts triples from new text and merges them into an existing ``GraphStoreBase``.

    Entity resolution policy: an incoming subject/object name is merged into
    an existing entity only on an exact (case/whitespace-insensitive) match
    against that entity's name or a known alias. Ambiguous cases (multiple
    existing entities share the name) are resolved conservatively by
    creating a new entity rather than risking a false merge between two
    distinct same-named entities — a false split is easier to fix later
    than a false merge that silently conflates two people/things.
    """

    def __init__(self, store: GraphStoreBase, llm: LLMProvider) -> None:
        self.store = store
        self.llm = llm

    def ingest(self, text: str, source_id: str) -> IngestResult:
        candidates = self.llm.extract_triples(text)
        result = IngestResult()

        new_entities: list[Entity] = []
        new_relations: list[Relation] = []

        def resolve(name: str) -> str:
            if name in result.entity_ids_by_name:
                return result.entity_ids_by_name[name]

            matches = self.store.find_entities_by_name(name)
            if len(matches) == 1:
                entity = matches[0]
                result.merged_entities += 1
            else:
                entity = Entity(name=name, type="unknown")
                new_entities.append(entity)
                result.new_entities += 1

            result.entity_ids_by_name[name] = entity.id
            return entity.id

        for candidate in candidates:
            subject_id = resolve(candidate.subject)
            object_id = resolve(candidate.object)
            new_relations.append(
                Relation(
                    subject_id=subject_id,
                    predicate=candidate.predicate,
                    object_id=object_id,
                    provenance=[
                        Provenance(source_id=source_id, source_span=candidate.source_span)
                    ],
                )
            )
            result.new_relations += 1

        if new_entities:
            self.store.add_entities(new_entities)
        if new_relations:
            self.store.add_relations(new_relations)

        return result
