import pytest

from benchmarks.loaders import DATA_DIR, load_locomo

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "locomo10.json").exists(),
    reason="run `python benchmarks/download_data.py` first",
)


def test_load_locomo_parses_real_dataset():
    conversations = load_locomo()
    assert len(conversations) == 10

    first = conversations[0]
    assert first.turns, "expected at least one dialogue turn"
    assert first.qa_pairs, "expected at least one QA pair"
    assert all(turn.turn_id and turn.speaker and turn.text for turn in first.turns[:5])

    qa = first.qa_pairs[0]
    assert qa.question
    assert qa.answer
