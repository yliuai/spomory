import asyncio

import pytest

pytest.importorskip("mcp")

from memory_core.audit import AuditLog
from memory_core.graph.local_store import LocalGraphStore
from memory_core.mcp_server.server import build_server
from memory_core.usage import UsageTracker
from tests.test_incremental import FakeLLMProvider


class FakeEmbeddingProvider:
    def embed(self, texts):
        import numpy as np

        # Deterministic, content-independent embedding: good enough to prove
        # the tool wiring works without pulling in a real model here.
        return np.array([[hash(t) % 997, 1.0] for t in texts], dtype=float)


def test_all_five_tools_are_registered():
    store = LocalGraphStore(":memory:")
    server = build_server(store, FakeLLMProvider([]), FakeEmbeddingProvider())

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "add_memory",
        "search_memory",
        "get_graph",
        "export_memory",
        "forget_memory",
    }


def test_add_memory_records_usage_when_tracker_given():
    store = LocalGraphStore(":memory:")
    from memory_core.llm.base import TripleCandidate

    llm = FakeLLMProvider(
        [TripleCandidate(subject="张三", predicate="任职于", object="某公司", source_span="s")]
    )
    tracker = UsageTracker(":memory:")
    server = build_server(store, llm, FakeEmbeddingProvider(), usage_tracker=tracker, user_id="u1")

    asyncio.run(server.call_tool("add_memory", {"text": "张三在某公司工作"}))

    assert tracker.event_count("u1", "add_memory") == 1
    assert tracker.active_users_since(7) == 1


def test_search_memory_records_a_retrieval_hit_on_the_matched_relation():
    """Epic 11.4: search_memory is the only place a relation's
    last_retrieved_at can get bumped, since that's what makes the passive
    staleness signal in ranker.py meaningful over time."""
    from memory_core.graph.models import Entity, Relation

    store = LocalGraphStore(":memory:")
    zhangsan = Entity(name="张三", type="person")
    company = Entity(name="某公司", type="organization")
    store.add_entities([zhangsan, company])
    relation = Relation(subject_id=zhangsan.id, predicate="任职于", object_id=company.id)
    store.add_relations([relation])
    assert relation.last_retrieved_at is None

    server = build_server(store, FakeLLMProvider([]), FakeEmbeddingProvider())
    asyncio.run(server.call_tool("search_memory", {"query": "张三 任职于 某公司"}))

    updated = next(r for r in store.all_relations() if r.id == relation.id)
    assert updated.last_retrieved_at is not None


def test_forget_memory_deletes_matched_relation_and_orphaned_entities():
    """Regression coverage for the gap the competitive analysis flagged:
    export_memory's "true delete" (Epic 7.3) existed at the storage layer
    but had no user-facing trigger -- a user had no way to say "forget that
    I work at X" from inside a conversation. forget_memory is that trigger.

    Also checks the orphan-cleanup side effect: an entity with no relations
    left after the deletion should be removed too, while an entity still
    touched by another relation must survive.
    """
    from memory_core.graph.models import Entity, Relation

    store = LocalGraphStore(":memory:")
    zhangsan = Entity(name="张三", type="person")
    company = Entity(name="某公司", type="organization")
    lisi = Entity(name="李四", type="person")
    store.add_entities([zhangsan, company, lisi])
    forgettable = Relation(subject_id=zhangsan.id, predicate="任职于", object_id=company.id)
    survivor = Relation(subject_id=lisi.id, predicate="喜欢", object_id=company.id)
    store.add_relations([forgettable, survivor])

    audit_log = AuditLog(":memory:")
    server = build_server(
        store, FakeLLMProvider([]), FakeEmbeddingProvider(), audit_log=audit_log, user_id="u1"
    )

    # Identical to _triple_text(forgettable, ...)'s rendering, so the fake
    # hash-based embedding gives it a perfect (1.0) cosine match -- the
    # highest score possible -- independent of hash randomization seed.
    result = asyncio.run(server.call_tool("forget_memory", {"query": "张三 任职于 某公司"}))
    assert "张三" in str(result) and "任职于" in str(result) and "某公司" in str(result)

    remaining_relation_ids = {r.id for r in store.all_relations()}
    assert forgettable.id not in remaining_relation_ids
    assert survivor.id in remaining_relation_ids

    remaining_entity_ids = {e.id for e in store.all_entities()}
    assert zhangsan.id not in remaining_entity_ids  # orphaned -> cleaned up
    assert company.id in remaining_entity_ids  # still touched by `survivor`
    assert lisi.id in remaining_entity_ids  # untouched

    records = audit_log.query("u1")
    assert len(records) == 1
    assert records[0].detail == {"entities_deleted": 1, "relations_deleted": 1}
