import pytest

from benchmarks.loaders import DATA_DIR, load_longmemeval

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "longmemeval_oracle.json").exists(),
    reason="run `python benchmarks/download_data.py` first",
)


def test_load_longmemeval_parses_real_dataset():
    conversations = load_longmemeval(limit=5)
    assert len(conversations) == 5

    first = conversations[0]
    assert first.turns, "expected at least one dialogue turn"
    assert len(first.qa_pairs) == 1
    assert first.qa_pairs[0].question
    assert first.qa_pairs[0].answer
    assert first.qa_pairs[0].evidence_turn_ids, "oracle variant should mark evidence turns"

    evidence_ids = set(first.qa_pairs[0].evidence_turn_ids)
    turn_ids = {t.turn_id for t in first.turns}
    assert evidence_ids <= turn_ids
