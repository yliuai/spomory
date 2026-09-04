"""Epic 5.1/5.3: does CLIP-based verification against the original image
actually catch textually-plausible-but-visually-wrong candidate triples
better than a text-only pipeline can?

Test design: each image gets its 2 real (ground-truth) candidate triples
plus 2 "distractor" triples borrowed from a *different* image's ground
truth — well-formed, plausible-sounding facts that simply aren't true of
*this* image. This is the exact failure class multimodal verification is
meant to catch (per the business plan's honest positioning: using raw
image/audio features to double-check text-mediated extraction, not
claiming native cross-modal extraction).

- "text-only" pipeline has no way to tell true from distractor and so
  accepts everything it extracted -> accuracy is fixed at true/total by
  construction (2/4 = 50% here), which is the point: it cannot filter.
- "CLIP-verified" pipeline scores all 4 candidates against the actual
  image and predicts the top-2 by score as the true ones.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_core.multimodal.clip_verification import ClipVerifier, triple_to_text

DATA_DIR = Path(__file__).parent / "data"
IMAGES_DIR = DATA_DIR / "images"
GROUND_TRUTH_PATH = DATA_DIR / "multimodal_ground_truth.json"


@dataclass
class ImageCase:
    filename: str
    true_triples: list[tuple[str, str, str]]
    distractor_triples: list[tuple[str, str, str]]


def build_cases() -> list[ImageCase]:
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text())
    filenames = list(ground_truth.keys())
    cases = []
    for i, filename in enumerate(filenames):
        true_triples = [tuple(t) for t in ground_truth[filename]["true_triples"]]
        distractor_filename = filenames[(i + 1) % len(filenames)]
        distractor_triples = [tuple(t) for t in ground_truth[distractor_filename]["true_triples"]]
        cases.append(
            ImageCase(filename=filename, true_triples=true_triples, distractor_triples=distractor_triples)
        )
    return cases


def evaluate(cases: list[ImageCase], verifier: ClipVerifier) -> dict:
    text_only_correct = 0
    clip_verified_correct = 0
    total_candidates = 0
    per_image = []

    for case in cases:
        candidates = case.true_triples + case.distractor_triples
        labels = [True] * len(case.true_triples) + [False] * len(case.distractor_triples)
        texts = [triple_to_text(*t) for t in candidates]

        # text-only: accepts every extracted candidate as-is (no filtering possible)
        text_only_predictions = [True] * len(candidates)
        text_only_correct += sum(p == l for p, l in zip(text_only_predictions, labels, strict=True))

        # CLIP-verified: predict the top-N (N = number of true triples) by score as true
        image_path = IMAGES_DIR / case.filename
        scores = [verifier.score(image_path, text) for text in texts]
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        top_n = set(ranked_indices[: len(case.true_triples)])
        clip_predictions = [i in top_n for i in range(len(candidates))]
        clip_verified_correct += sum(
            p == l for p, l in zip(clip_predictions, labels, strict=True)
        )

        total_candidates += len(candidates)
        per_image.append(
            {
                "filename": case.filename,
                "candidates": texts,
                "labels": labels,
                "clip_scores": scores,
                "clip_predictions": clip_predictions,
            }
        )

    return {
        "n_images": len(cases),
        "n_candidates": total_candidates,
        "text_only_accuracy": text_only_correct / total_candidates,
        "clip_verified_accuracy": clip_verified_correct / total_candidates,
        "per_image": per_image,
    }


if __name__ == "__main__":
    cases = build_cases()
    verifier = ClipVerifier()
    report = evaluate(cases, verifier)

    print(f"images={report['n_images']} candidates={report['n_candidates']}")
    print(f"text-only accuracy:     {report['text_only_accuracy']:.2%}")
    print(f"CLIP-verified accuracy: {report['clip_verified_accuracy']:.2%}")

    out_path = Path(__file__).parent / "results" / "multimodal_eval.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Wrote {out_path}")
