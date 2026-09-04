import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmarks"))

from multimodal_eval import GROUND_TRUTH_PATH, build_cases, evaluate


def test_build_cases_pairs_each_image_with_a_different_images_distractors():
    cases = build_cases()
    filenames = json.loads(GROUND_TRUTH_PATH.read_text()).keys()
    assert len(cases) == len(list(filenames))
    for case in cases:
        assert len(case.true_triples) == 2
        assert len(case.distractor_triples) == 2
        # distractors must not equal the true triples (would defeat the test)
        assert set(case.distractor_triples).isdisjoint(set(case.true_triples))


class FakeVerifier:
    """Scores a text 1.0 if it names an entity that's actually in the image
    filename's "true" set (by convention: filename encodes which case it's
    for via the caller), else 0.0 — a stand-in for CLIP so this test doesn't
    need to download a model or touch real image files."""

    def __init__(self, correct_texts: set[str]) -> None:
        self.correct_texts = correct_texts

    def score(self, image_path, text: str) -> float:
        return 1.0 if text in self.correct_texts else 0.0


def test_evaluate_perfect_verifier_beats_text_only_baseline():
    cases = build_cases()[:2]  # keep it small and fast
    correct_texts = {
        f"{s} {p} {o}" for case in cases for (s, p, o) in case.true_triples
    }
    verifier = FakeVerifier(correct_texts)

    report = evaluate(cases, verifier)

    assert report["n_images"] == 2
    assert report["n_candidates"] == 8  # 2 true + 2 distractor per image
    assert report["text_only_accuracy"] == 0.5  # accepts everything -> true/total
    assert report["clip_verified_accuracy"] == 1.0  # perfect verifier separates them fully
