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

_NEGATIVE_MARKERS = ("不采纳", "不应该", "不建议", "拒绝", "NOOP", "否")
_POSITIVE_MARKERS = ("采纳", "应该", "同意", "ADD", "是")


def _completion_adopts_the_action(text: str) -> bool:
    """Parse whether a completion says "yes, adopt this memory operation" or
    "no, don't" — checked against the training prompts' closing question
    ("是否应该采纳这个记忆操作？"). Negative markers are checked first since
    e.g. "不应该采纳" contains the positive substring "应该采纳" too.
    """
    if any(marker in text for marker in _NEGATIVE_MARKERS):
        return False
    return any(marker in text for marker in _POSITIVE_MARKERS)


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

    Each of GRPO's ``num_generations`` samples for the same prompt gets
    scored on what THAT completion actually said, not a single value
    repeated across the group — repeating a per-prompt constant here would
    give every sample in a group identical reward, making GRPO's
    within-group advantage (and hence the gradient) permanently zero
    regardless of dataset size. Reward is 1 when the completion's own
    adopt/reject decision matches whether adopting this candidate fact
    actually helped downstream QA (the `qa_correct` label recorded when the
    dataset was built): if the fact turned out useful, the model should
    have said "adopt"; if not, it should have said "reject".
    """
    qa_correct_labels = kwargs.get("qa_correct", [False] * len(completions))
    rewards = []
    for completion, correct in zip(completions, qa_correct_labels, strict=True):
        adopted = _completion_adopts_the_action(completion)
        episode = Episode(episode_id="0", qa_correct=(adopted == bool(correct)))
        rewards.append(compute_reward(episode))
    return rewards


def build_trainer(
    base_model: str,
    dataset: Dataset,
    output_dir: str,
    lora_r: int = 16,
) -> GRPOTrainer:
    import torch

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_r * 2,
        target_modules=["q_proj", "v_proj"],
        task_type="CAUSAL_LM",
    )
    # device_map={"": 0}: force the whole model onto one GPU. Without it,
    # transformers' big-model loading heuristics can offload some layers to
    # a "meta" device, which then crashes backward() with a device mismatch
    # between the LoRA gradient and the offloaded weight. Only applies when
    # CUDA is actually available -- the CPU-only smoke test (tiny placeholder
    # model, no GPU) needs the default (no device_map) behavior instead.
    model_init_kwargs = {"torch_dtype": "bfloat16" if torch.cuda.is_available() else "float32"}
    if torch.cuda.is_available():
        # "auto": shard across every visible GPU (accelerate's dispatch) so a
        # 7B model + on-policy generation buffers aren't squeezed onto one
        # 24GB card. {"":0} above was simpler but OOM'd on a single GPU.
        model_init_kwargs["device_map"] = "auto"
    grpo_config = GRPOConfig(
        output_dir=output_dir,
        num_generations=4,
        per_device_train_batch_size=4,
        max_completion_length=64,
        model_init_kwargs=model_init_kwargs,
        bf16=torch.cuda.is_available(),
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
