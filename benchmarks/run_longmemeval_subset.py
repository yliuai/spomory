"""Epic 11.1's LongMemEval re-run: the LoCoMo side of Epic 11.1 was already
done (see docs/benchmark_smoke_test.md); this is the LongMemEval half that
was still outstanding, using the existing Epic 4.1 harness against a subset
of LongMemEval's "oracle" variant (github.com/xiaowu0162/LongMemEval).

Unlike LoCoMo (one long conversation, many QA pairs sharing ingested turns),
each LongMemEval oracle question comes with its own independent haystack --
loaders.load_longmemeval already models that as one single-QA-pair
Conversation per question, so this runs harness.run_conversation() once per
question and aggregates across all of them, rather than once for a shared
conversation.

Sample size (10 questions, not the full 500) is a deliberate, real
constraint, not an oversight: this environment's LLM API calls go through a
proxy with real latency (~38s/call observed during the LoCoMo re-run), and
each question ingests ~27 turns on average -- the full dataset would run for
many hours. 10 questions is small enough to actually finish in one session
while still being a real end-to-end run, not a mock.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from benchmarks.harness import exact_or_substring_match, make_llm_judge_scorer, run_conversation
from benchmarks.loaders import load_longmemeval
from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
from memory_core.llm.openai_compatible import OpenAICompatibleProvider

N_QUESTIONS = 10
OUT_PATH = Path("benchmarks/results/longmemeval_oracle_subset.json")


def main() -> None:
    conversations = load_longmemeval(limit=N_QUESTIONS)
    assert len(conversations) == N_QUESTIONS

    llm = OpenAICompatibleProvider()
    embedder = SentenceTransformerProvider()
    judge = make_llm_judge_scorer(llm)

    start = time.time()
    per_type: dict[str, dict[str, int]] = {}
    cases_out = []
    recall_hits = 0
    strict_hits = 0
    judge_hits = 0

    for conv in conversations:
        result = run_conversation(conv, llm, embedder, top_k=10, scorer=exact_or_substring_match)
        qa = conv.qa_pairs[0]
        case = result.cases[0]
        judged_correct = judge(case.predicted_answer, qa.answer)

        recall_hits += int(case.retrieved_evidence_hit)
        strict_hits += int(case.correct)
        judge_hits += int(judged_correct)

        qtype = str(qa.category)
        bucket = per_type.setdefault(
            qtype, {"n": 0, "recall": 0, "correct_strict": 0, "correct_llm_judge": 0}
        )
        bucket["n"] += 1
        bucket["recall"] += int(case.retrieved_evidence_hit)
        bucket["correct_strict"] += int(case.correct)
        bucket["correct_llm_judge"] += int(judged_correct)

        cases_out.append(
            {
                "sample_id": conv.sample_id,
                "question_type": qa.category,
                "question": case.question,
                "gold_answer": qa.answer,
                "predicted_answer": case.predicted_answer,
                "retrieved_evidence_hit": case.retrieved_evidence_hit,
                "correct_strict": case.correct,
                "correct_llm_judge": judged_correct,
            }
        )
        print(
            f"[{len(cases_out)}/{N_QUESTIONS}] recall_hit={case.retrieved_evidence_hit} "
            f"strict={case.correct} judge={judged_correct}"
        )

    elapsed = time.time() - start

    output = {
        "dataset": f"longmemeval_oracle.json[:{N_QUESTIONS}]",
        "n_questions": N_QUESTIONS,
        "recall_at_10": recall_hits / N_QUESTIONS,
        "accuracy_strict": strict_hits / N_QUESTIONS,
        "accuracy_llm_judge": judge_hits / N_QUESTIONS,
        "elapsed_seconds": elapsed,
        "note": (
            f"Epic 11.1: a {N_QUESTIONS}-question subset of LongMemEval's 500-question "
            "oracle variant, not the full dataset -- this environment's LLM API calls "
            "go through a proxy with real per-call latency, and the full dataset would "
            "take many hours. Recall@10/accuracy numbers below are honest for this "
            "sample size, not claimed to generalize to the full 500."
        ),
        "per_question_type": {
            qtype: {
                "n": v["n"],
                "recall_at_10": v["recall"] / v["n"],
                "accuracy_strict": v["correct_strict"] / v["n"],
                "accuracy_llm_judge": v["correct_llm_judge"] / v["n"],
            }
            for qtype, v in sorted(per_type.items())
        },
        "cases": cases_out,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"done in {elapsed:.0f}s")
    print(
        f"recall@10={output['recall_at_10']:.2%} "
        f"accuracy_strict={output['accuracy_strict']:.2%} "
        f"accuracy_llm_judge={output['accuracy_llm_judge']:.2%}"
    )
    print("per_question_type:")
    for qtype, v in output["per_question_type"].items():
        print(f"  {qtype}: n={v['n']} recall@10={v['recall_at_10']:.2%} llm_judge={v['accuracy_llm_judge']:.2%}")
    print(f"written to {OUT_PATH}")


if __name__ == "__main__":
    main()
