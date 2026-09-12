"""Incremental write/merge logic.

Only the newly-extracted triples are touched on each call — there is no
step here that re-reads or re-derives the rest of the graph, which is the
property that makes this "incremental" rather than an indexer that
rebuilds everything (the LightRAG-style design choice called out in the
business plan, as opposed to GraphRAG's full-rebuild-per-update approach).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from memory_core.llm.base import LLMProvider

from .models import Entity, Provenance, Relation
from .store import GraphStoreBase

if TYPE_CHECKING:
    from memory_core.memory_manager.policy import MemoryPolicy


# Epic 12.4: exact-match, case/punctuation-insensitive filler phrases that
# carry no extractable fact -- deliberately a small, conservative allowlist
# rather than a length threshold or fuzzy match, so a short but meaningful
# sentence ("I quit.") is never mistaken for filler. Skipping these avoids
# an LLM extraction call (real money, and the only thing standing between a
# public endpoint like /demo/try and a free way to burn API budget) for
# input that could never contain a triple anyway.
_LOW_INFORMATION_PHRASES = {
    "thanks",
    "thank you",
    "ok",
    "okay",
    "got it",
    "sounds good",
    "sure",
    "yes",
    "no",
    "hi",
    "hello",
    "bye",
    "goodbye",
    "谢谢",
    "谢谢你",
    "好的",
    "好",
    "嗯",
    "在吗",
    "在",
    "明白",
    "明白了",
    "知道了",
    "收到",
}

_STRIP_CHARS = " \t\n\r!?。！？.,，、~～"


def _is_low_information(text: str) -> bool:
    normalized = text.strip(_STRIP_CHARS).lower()
    return normalized in _LOW_INFORMATION_PHRASES


@dataclass
class IngestResult:
    new_entities: int = 0
    merged_entities: int = 0
    new_relations: int = 0
    updated_relations: int = 0
    noop_relations: int = 0
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

    def __init__(
        self, store: GraphStoreBase, llm: LLMProvider, policy: MemoryPolicy | None = None
    ) -> None:
        """``policy`` (Epic 3.2/3.5): when given, every extracted candidate is
        routed through ``policy.decide()`` (ADD/UPDATE/DELETE/NOOP) instead of
        being unconditionally written — this is what actually wires Epic 3's
        memory-management layer into the ingestion path Epic 1+2 use, rather
        than leaving it a standalone, never-called module. Defaults to
        ``None`` (unconditional add/merge) to keep existing callers'
        behavior unchanged.
        """
        self.store = store
        self.llm = llm
        self.policy = policy

    def ingest(self, text: str, source_id: str) -> IngestResult:
        result = IngestResult()
        if _is_low_information(text):
            return result

        candidates = self.llm.extract_triples(text)

        new_entities: list[Entity] = []
        pending_relations: list[Relation] = []

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
            relation = Relation(
                subject_id=subject_id,
                predicate=candidate.predicate,
                object_id=object_id,
                provenance=[Provenance(source_id=source_id, source_span=candidate.source_span)],
            )

            if self.policy is None:
                pending_relations.append(relation)
                result.new_relations += 1
                continue

            # New entities must be visible to the store before the policy can
            # meaningfully query "what do we already know about this subject"
            # (get_neighbors), so flush them immediately rather than batching.
            if new_entities:
                self.store.add_entities(new_entities)
                new_entities = []
            self._apply_via_policy(relation, result)

        if new_entities:
            self.store.add_entities(new_entities)
        if pending_relations:
            self.store.add_relations(pending_relations)

        return result

    def _apply_via_policy(self, relation: Relation, result: IngestResult) -> None:
        from memory_core.memory_manager.actions import ActionType, apply_action

        action = self.policy.decide(relation, self.store)
        apply_action(action, self.store)

        if action.action_type is ActionType.ADD:
            result.new_relations += 1
        elif action.action_type is ActionType.UPDATE:
            result.updated_relations += 1
        elif action.action_type is ActionType.NOOP:
            result.noop_relations += 1
        # DELETE isn't reachable from RuleBasedPolicy's own candidate-vs-existing
        # comparison today, but is handled uniformly by apply_action() either way.
