import time

from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity
from memory_core.llm.base import LLMProvider, TripleCandidate


class FakeLLMProvider(LLMProvider):
    """Returns a fixed, caller-supplied list of triples instead of calling a real API."""

    def __init__(self, triples: list[TripleCandidate]) -> None:
        self._triples = triples
        self.extract_triples_calls = 0
        self.last_text: str | None = None

    def extract_triples(self, text: str) -> list[TripleCandidate]:
        self.extract_triples_calls += 1
        self.last_text = text
        return self._triples

    def generate(self, prompt: str, **kwargs: object) -> str:
        raise NotImplementedError


def _triple(s: str, p: str, o: str) -> TripleCandidate:
    return TripleCandidate(subject=s, predicate=p, object=o, source_span=f"{s} {p} {o}")


def test_three_batches_produce_expected_counts(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")

    batch1 = [_triple("张三", "任职于", "某公司")]
    batch2 = [_triple("张三", "居住在", "北京"), _triple("李四", "任职于", "某公司")]
    # third batch re-mentions 张三 and 某公司: should merge, not duplicate
    batch3 = [_triple("张三", "认识", "李四")]

    ingestor = IncrementalIngestor(store, FakeLLMProvider(batch1))
    r1 = ingestor.ingest("doc one", source_id="doc-1")
    assert r1.new_entities == 2  # 张三, 某公司
    assert r1.new_relations == 1

    ingestor.llm = FakeLLMProvider(batch2)
    r2 = ingestor.ingest("doc two", source_id="doc-2")
    assert r2.new_entities == 2  # 北京, 李四
    assert r2.merged_entities == 2  # 张三, 某公司 reused
    assert r2.new_relations == 2

    ingestor.llm = FakeLLMProvider(batch3)
    r3 = ingestor.ingest("doc three", source_id="doc-3")
    assert r3.new_entities == 0
    assert r3.merged_entities == 2  # 张三, 李四 reused
    assert r3.new_relations == 1

    assert len(store.all_entities()) == 4  # 张三, 某公司, 北京, 李四
    assert len(store.all_relations()) == 4


def test_ingest_skips_llm_call_for_low_information_filler(tmp_path):
    """Epic 12.4: filler like "thanks"/"好的" can never contain an
    extractable fact, so it should never reach the LLM -- both to save the
    API call's cost and because a public, unauthenticated endpoint (e.g.
    /demo/try) would otherwise let anyone burn real API budget by spamming
    filler.
    """
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    llm = FakeLLMProvider([_triple("x", "y", "z")])
    ingestor = IncrementalIngestor(store, llm)

    for filler in ["thanks", "  OK.  ", "好的！", "谢谢你", "在吗"]:
        result = ingestor.ingest(filler, source_id="doc-filler")
        assert result.new_relations == 0
        assert result.new_entities == 0

    assert llm.extract_triples_calls == 0
    assert store.all_relations() == []


def test_ingest_still_extracts_short_but_meaningful_text(tmp_path):
    """Guards against the filter being too aggressive: a short sentence
    that happens to contain a real fact must still reach the LLM."""
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    llm = FakeLLMProvider([_triple("我", "辞职了", "")])
    ingestor = IncrementalIngestor(store, llm)

    ingestor.ingest("我辞职了。", source_id="doc-real")

    assert llm.extract_triples_calls == 1


def test_ingest_redacts_secrets_before_the_llm_call(tmp_path):
    """Epic 13.1: a secret pasted into a message must never reach the
    extraction LLM in plaintext -- only the matched token is replaced, the
    surrounding fact ("the key is used in auth.ts") still reaches the LLM."""
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    llm = FakeLLMProvider([_triple("我", "使用", "密钥")])
    ingestor = IncrementalIngestor(store, llm)

    secret = "sk-ant-api03-" + "x" * 40
    ingestor.ingest(f"密钥是 {secret}，用在 auth.ts 里", source_id="doc-secret")

    assert secret not in llm.last_text
    assert "REDACTED" in llm.last_text
    assert "auth.ts" in llm.last_text  # surrounding fact is preserved


def test_incremental_write_time_does_not_blow_up_with_graph_size(tmp_path):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    store.add_entities([Entity(name=f"filler-{i}", type="thing") for i in range(2000)])

    ingestor = IncrementalIngestor(store, FakeLLMProvider([_triple("新实体A", "关联", "新实体B")]))

    start = time.perf_counter()
    ingestor.ingest("small new fact", source_id="doc-x")
    elapsed = time.perf_counter() - start

    # A single small incremental write against a few-thousand-node graph
    # should stay well under a second; it must never approach "rebuild the
    # whole graph" territory.
    assert elapsed < 2.0
