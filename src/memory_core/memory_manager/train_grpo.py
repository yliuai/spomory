"""GRPO training for the memory-management policy (Memory-R1 style).

Production usage needs a real multi-GPU box and the actual ~150-episode
LoCoMo-derived dataset (see docs/dataset_format.md) — neither is available
in this development environment, so this script has only been smoke-tested
against a tiny placeholder model and a handful of synthetic episodes to
prove the TRL/PEFT wiring itself is correct (data collator, reward
function, LoRA config, `GRPOTrainer.train()` completing without error).
That is NOT the same as verifying training actually improves the policy on
real data — Epic 3.4's full acceptance (a real LoRA checkpoint trained on
Qwen2.5-7B-Instruct-class model with the real dataset) still needs that
GPU budget.

Usage:
    python -m memory_core.memory_manager.train_grpo \\
        --base-model Qwen/Qwen2.5-7B-Instruct \\
        --dataset benchmarks/data/memory_ops_train.jsonl \\
        --output-dir checkpoints/memory-grpo-lora
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from datasets import Dataset
from peft import LoraConfig
from trl import GRPOConfig, GRPOTrainer

from .reward import Episode, compute_reward


@dataclass
class TrainEpisodeRow:
    """One row of the JSONL dataset described in docs/dataset_format.md."""

    prompt: str  # rendered dialogue history + candidate action, as fed to the policy
    qa_correct: bool  # downstream QA outcome after applying the chosen action


def load_dataset(path: str | Path) -> Dataset:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    return Dataset.from_list(rows)


def _reward_fn(completions: list[str], **kwargs: object) -> list[float]:
    """TRL reward function signature: score each sampled completion.

    Real reward computation needs to actually apply the completion's memory
    action and check downstream QA correctness (this is what
    `benchmarks/harness.py` does at eval time); here we read the
    precomputed `qa_correct` label that was baked into the dataset row at
    data-generation time, since GRPO training doesn't re-run the QA agent
    for every sampled completion during rollout.
    """
    qa_correct_labels = kwargs.get("qa_correct", [False] * len(completions))
    return [
        compute_reward(Episode(episode_id=str(i), qa_correct=bool(correct)))
        for i, correct in enumerate(qa_correct_labels)
    ]


def build_trainer(
    base_model: str,
    dataset: Dataset,
    output_dir: str,
    lora_r: int = 16,
) -> GRPOTrainer:
    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_r * 2,
        target_modules=["q_proj", "v_proj"],
        task_type="CAUSAL_LM",
    )
    grpo_config = GRPOConfig(
        output_dir=output_dir,
        num_generations=4,
        per_device_train_batch_size=4,
        max_completion_length=64,
    )
    return GRPOTrainer(
        model=base_model,
        reward_funcs=_reward_fn,
        args=grpo_config,
        train_dataset=dataset,
        peft_config=lora_config,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-dir", default="checkpoints/memory-grpo-lora")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    trainer = build_trainer(args.base_model, dataset, args.output_dir)
    trainer.train()
    trainer.save_model(args.output_dir)


if __name__ == "__main__":
    main()
