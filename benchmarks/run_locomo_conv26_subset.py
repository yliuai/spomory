"""Re-run of the Epic 4.2 84-QA-pair LoCoMo benchmark (docs/benchmark_smoke_test.md),
after the extraction-prompt fix that folds dates into the predicate
(llm/openai_compatible.py). The original run predates that fix; this
re-run exists to confirm whether it actually moves category 2 (time
reasoning) and the overall LLM-judge accuracy, as flagged in
TASKS.md Epic 11.1.

Reuses harness.run_conversation for ingestion/retrieval/generation with
the strict scorer, then re-scores each already-generated answer with the
LLM-judge scorer (no extra generation calls) to get both accuracy numbers
from a single pass, matching the shape of the original locomo_full_run.json.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from benchmarks.harness import exact_or_substring_match, make_llm_judge_scorer, run_conversation
from benchmarks.loaders import Conversation, load_locomo
from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
from memory_core.llm.openai_compatible import OpenAICompatibleProvider

OUT_PATH = Path("benchmarks/results/locomo_full_run_after_date_fix.json")


def main() -> None:
    conversations = load_locomo()
    conv = conversations[0]
    assert conv.sample_id == "conv-26"

    turns_150 = conv.turns[:150]
    turn_ids_150 = {t.turn_id for t in turns_150}
    qa_pairs = [
        qa
        for qa in conv.qa_pairs
        if qa.evidence_turn_ids and set(qa.evidence_turn_ids).issubset(turn_ids_150)
    ]
    assert len(qa_pairs) == 84, f"expected 84 QA pairs, got {len(qa_pairs)}"

    subset = Conversation(sample_id=conv.sample_id, turns=turns_150, qa_pairs=qa_pairs)

    llm = OpenAICompatibleProvider()
    embedder = SentenceTransformerProvider()

    start = time.time()
    result = run_conversation(subset, llm, embedder, top_k=10, scorer=exact_or_substring_match)
    judge = make_llm_judge_scorer(llm)

    per_category: dict[str, dict[str, int]] = {}
    llm_judge_hits = 0
    cases_out = []
    for case, qa in zip(result.cases, qa_pairs, strict=True):
        judged_correct = judge(case.predicted_answer, qa.answer)
        llm_judge_hits += int(judged_correct)
        cat = str(qa.category)
        bucket = per_category.setdefault(cat, {"n": 0, "correct_strict": 0, "correct_llm_judge": 0})
        bucket["n"] += 1
        bucket["correct_strict"] += int(case.correct)
        bucket["correct_llm_judge"] += int(judged_correct)
        cases_out.append(
            {
                "question": case.question,
                "category": qa.category,
                "gold_answer": qa.answer,
                "predicted_answer": case.predicted_answer,
                "retrieved_evidence_hit": case.retrieved_evidence_hit,
                "correct_strict": case.correct,
                "correct_llm_judge": judged_correct,
            }
        )

    elapsed = time.time() - start

    output = {
        "dataset": "locomo10:conv-26:turns[:150]",
        "sample_id": conv.sample_id,
        "n_turns_ingested": len(turns_150),
        "n_qa_pairs": len(qa_pairs),
        "recall_at_10": result.recall_at_k,
        "accuracy_strict": result.accuracy,
        "accuracy_llm_judge": llm_judge_hits / len(qa_pairs),
        "elapsed_seconds": elapsed,
        "note": (
            "Re-run after the date-into-predicate extraction fix "
            "(llm/openai_compatible.py), to check whether it moves category 2 "
            "(time reasoning) vs the original pre-fix run in locomo_full_run.json."
        ),
        "per_category": {
            cat: {
                "n": v["n"],
                "accuracy_strict": v["correct_strict"] / v["n"],
                "accuracy_llm_judge": v["correct_llm_judge"] / v["n"],
            }
            for cat, v in sorted(per_category.items())
        },
        "cases": cases_out,
        "partial": False,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"done in {elapsed:.0f}s")
    print(f"recall@10={output['recall_at_10']:.2%} "
          f"accuracy_strict={output['accuracy_strict']:.2%} "
          f"accuracy_llm_judge={output['accuracy_llm_judge']:.2%}")
    print("per_category:")
    for cat, v in output["per_category"].items():
        print(f"  category {cat}: n={v['n']} llm_judge={v['accuracy_llm_judge']:.2%}")
    print(f"written to {OUT_PATH}")


if __name__ == "__main__":
    main()
