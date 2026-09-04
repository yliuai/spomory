"""Proves Epic 3's policy layer actually drives IncrementalIngestor's writes
(closing the "Epic 1+2+3 assembled pipeline" gap Epic 4.2 asks for), not just
that RuleBasedPolicy works in isolation against a pre-built store.
"""

from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.memory_manager.policy import RuleBasedPolicy
from tests.test_incremental import FakeLLMProvider, _triple


def test_duplicate_fact_across_two_ingest_calls_becomes_noop_not_a_new_relation():
    store = LocalGraphStore(":memory:")
    policy = RuleBasedPolicy()

    ingestor = IncrementalIngestor(store, FakeLLMProvider([_triple("张三", "任职于", "某公司")]), policy)
    r1 = ingestor.ingest("doc one", source_id="doc-1")
    assert r1.new_relations == 1

    # same fact again, in a later call -> policy should NOOP it, not duplicate
    r2 = ingestor.ingest("doc two (same fact repeated)", source_id="doc-2")
    assert r2.noop_relations == 1
    assert r2.new_relations == 0
    assert len(store.all_relations()) == 1  # not duplicated


def test_conflicting_fact_becomes_an_update_not_a_second_relation():
    store = LocalGraphStore(":memory:")
    policy = RuleBasedPolicy()
    ingestor = IncrementalIngestor(store, FakeLLMProvider([]), policy)

    ingestor.llm = FakeLLMProvider([_triple("张三", "任职于", "老公司")])
    ingestor.ingest("张三在老公司工作", source_id="doc-1")

    ingestor.llm = FakeLLMProvider([_triple("张三", "任职于", "新公司")])
    result = ingestor.ingest("张三换工作去了新公司", source_id="doc-2")

    assert result.updated_relations == 1
    relations = store.all_relations()
    assert len(relations) == 1  # updated in place, not appended
    new_company = next(e for e in store.all_entities() if e.name == "新公司")
    assert relations[0].object_id == new_company.id


def test_no_policy_keeps_old_always_add_behavior():
    store = LocalGraphStore(":memory:")
    ingestor = IncrementalIngestor(store, FakeLLMProvider([_triple("a", "r", "b")]))  # policy=None

    ingestor.ingest("doc one", source_id="doc-1")
    ingestor.ingest("doc two (same fact repeated)", source_id="doc-2")

    assert len(store.all_relations()) == 2  # unconditional add, unchanged default behavior
