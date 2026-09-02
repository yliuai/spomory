"""Epic 1.6: edge cases for entity resolution during incremental merge."""

from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity
from tests.test_incremental import FakeLLMProvider, _triple


def test_alias_merges_into_existing_entity(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    existing = Entity(name="张三", type="person", aliases=["Zhang San"])
    store.add_entities([existing])

    ingestor = IncrementalIngestor(
        store, FakeLLMProvider([_triple("Zhang San", "任职于", "某公司")])
    )
    result = ingestor.ingest("doc", source_id="doc-1")

    assert result.merged_entities == 1  # matched via alias, not a duplicate
    assert result.new_entities == 1  # 某公司 only
    assert len(store.all_entities()) == 2


def test_ambiguous_same_name_does_not_false_merge(tmp_path):
    """Two pre-existing, genuinely distinct entities happen to share a name.

    The resolver must not silently pick one of them (that would conflate two
    different people/things); it creates a new entity instead, which is a
    safer failure mode than a false merge.
    """
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    store.add_entities(
        [
            Entity(name="张三", type="person", attributes={"company": "公司A"}),
            Entity(name="张三", type="person", attributes={"company": "公司B"}),
        ]
    )

    ingestor = IncrementalIngestor(store, FakeLLMProvider([_triple("张三", "任职于", "公司C")]))
    result = ingestor.ingest("doc", source_id="doc-1")

    assert result.merged_entities == 0
    assert result.new_entities == 2  # a fresh 张三, plus 公司C
    names = [e.name for e in store.all_entities()]
    assert names.count("张三") == 3


def test_case_and_whitespace_insensitive_merge(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    existing = Entity(name="OpenAI", type="organization")
    store.add_entities([existing])

    ingestor = IncrementalIngestor(
        store, FakeLLMProvider([_triple("张三", "任职于", "  openai  ")])
    )
    result = ingestor.ingest("doc", source_id="doc-1")

    assert result.merged_entities == 1
    assert len(store.all_entities()) == 2
