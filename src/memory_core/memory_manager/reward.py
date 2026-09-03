"""Result-oriented reward for GRPO training of the memory-management policy.

Deliberately a single downstream-QA-correctness signal, not Mem-alpha's
four-way reward split — per the business plan, that's the cheaper-to-adopt
entry point for a resource-constrained team, at the cost of a less granular
training signal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Episode:
    """One (memory operations -> downstream QA outcome) training sample."""

    episode_id: str
    qa_correct: bool


def compute_reward(episode: Episode) -> float:
    """0/1 reward: did the downstream QA that followed this memory-op sequence succeed?"""
    return 1.0 if episode.qa_correct else 0.0


def compute_rewards(episodes: list[Episode]) -> list[float]:
    return [compute_reward(e) for e in episodes]
