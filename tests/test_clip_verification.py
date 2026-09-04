from pathlib import Path

import pytest

pytest.importorskip("transformers")
pytest.importorskip("PIL")

IMAGES_DIR = Path(__file__).parent.parent / "benchmarks" / "data" / "images"

pytestmark = pytest.mark.skipif(
    not (IMAGES_DIR / "picsum_237.jpg").exists(),
    reason="test images not present (see benchmarks/data/images/)",
)


@pytest.mark.slow
def test_clip_scores_matching_text_higher_than_unrelated_text():
    from memory_core.multimodal.clip_verification import ClipVerifier

    verifier = ClipVerifier()
    image_path = IMAGES_DIR / "picsum_237.jpg"  # a black puppy on a wooden floor

    matching = verifier.score(image_path, "a black puppy sitting on a wooden floor")
    unrelated = verifier.score(image_path, "a pile of red strawberries")

    assert matching > unrelated


@pytest.mark.slow
def test_rank_orders_candidates_by_relevance():
    from memory_core.multimodal.clip_verification import ClipVerifier

    verifier = ClipVerifier()
    image_path = IMAGES_DIR / "picsum_1069.jpg"  # an orange jellyfish in blue water

    ranked = verifier.rank(
        image_path,
        ["an orange jellyfish swimming in water", "a white castle on a hill", "a lion's face"],
    )

    assert ranked[0][0] == "an orange jellyfish swimming in water"
