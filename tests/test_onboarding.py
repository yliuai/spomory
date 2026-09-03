from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.llm.base import TripleCandidate
from memory_core.onboarding import import_directory
from tests.test_incremental import FakeLLMProvider


def test_imports_20_markdown_files_and_makes_them_queryable(tmp_path):
    for i in range(20):
        (tmp_path / f"note-{i}.md").write_text(f"项目{i}的负责人是工程师{i}。")
    # a couple of non-note files that should be skipped, not error out
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "empty.txt").write_text("   ")

    store = LocalGraphStore(":memory:")
    triples_by_call = iter(
        [TripleCandidate(subject=f"项目{i}", predicate="负责人是", object=f"工程师{i}", source_span=f"项目{i}的负责人是工程师{i}。")]
        for i in range(20)
    )

    class SequencedLLM(FakeLLMProvider):
        def extract_triples(self, text: str) -> list[TripleCandidate]:
            return next(triples_by_call)

    ingestor = IncrementalIngestor(store, SequencedLLM([]))
    summary = import_directory(tmp_path, ingestor)

    assert summary.files_imported == 20
    assert set(summary.files_skipped) == {"diagram.png", "empty.txt"}
    assert summary.total_new_relations == 20

    # queryable: e.g. 项目5's owner made it into the graph
    matches = store.find_entities_by_name("项目5")
    assert matches
    neighbors = store.get_neighbors(matches[0].id)
    assert any(r.predicate == "负责人是" for r in neighbors)
