"""Action-selection policies: a rule-based baseline (Epic 3.2's default) and
a GRPO-trained model wrapper that Epic 3.6 compares it against.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from memory_core.graph.models import Relation
from memory_core.graph.store import GraphStoreBase

from .actions import ActionType, MemoryAction


class MemoryPolicy(ABC):
    @abstractmethod
    def decide(self, candidate: Relation, store: GraphStoreBase) -> MemoryAction:
        raise NotImplementedError


class RuleBasedPolicy(MemoryPolicy):
    """Heuristic baseline: ADD anything new; if a relation already exists with
    the same subject+predicate but a different object, UPDATE it (the fact
    changed — e.g. a new job replaces an old one); otherwise NOOP on exact
    duplicates. Never DELETEs on its own (no rule can safely infer "this is
    now false" from one new sentence) — that's exactly the gap Epic 3's GRPO
    policy is meant to fill in over this baseline.
    """

    def decide(self, candidate: Relation, store: GraphStoreBase) -> MemoryAction:
        existing = [
            r
            for r in store.get_neighbors(candidate.subject_id)
            if r.subject_id == candidate.subject_id and r.predicate == candidate.predicate
        ]

        if not existing:
            return MemoryAction(ActionType.ADD, relation=candidate)

        same = next((r for r in existing if r.object_id == candidate.object_id), None)
        if same is not None:
            return MemoryAction(ActionType.NOOP)

        outdated = existing[0]
        return MemoryAction(
            ActionType.UPDATE,
            target_id=outdated.id,
            updates={"object_id": candidate.object_id, "provenance": candidate.provenance},
        )


class TrainedPolicy(MemoryPolicy):
    """Wraps a GRPO-trained (base model + LoRA adapter) checkpoint from
    ``train_grpo.py``. Parses the model's free-text decision into an
    ``ActionType`` via a fixed keyword protocol the training prompts must
    also use, since GRPO trains against exactly that reward signal.
    """

    def __init__(self, checkpoint_dir: str, base_model: str | None = None) -> None:
        from peft import AutoPeftModelForCausalLM
        from transformers import AutoTokenizer

        self.model = AutoPeftModelForCausalLM.from_pretrained(checkpoint_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)

    def _render_prompt(self, candidate: Relation, existing: list[Relation]) -> str:
        existing_text = "；".join(f"{r.predicate}->{r.object_id}" for r in existing) or "无"
        return (
            f"候选事实：{candidate.subject_id} {candidate.predicate} {candidate.object_id}。"
            f"已有相关记忆：{existing_text}。"
            "请从 ADD/UPDATE/DELETE/NOOP 中选择一个动作。"
        )

    def decide(self, candidate: Relation, store: GraphStoreBase) -> MemoryAction:
        existing = store.get_neighbors(candidate.subject_id)
        prompt = self._render_prompt(candidate, existing)

        inputs = self.tokenizer(prompt, return_tensors="pt")
        output_ids = self.model.generate(**inputs, max_new_tokens=8)
        decision_text = self.tokenizer.decode(
            output_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )

        for action_type in ActionType:
            if action_type.value in decision_text.upper():
                if action_type is ActionType.ADD:
                    return MemoryAction(ActionType.ADD, relation=candidate)
                if action_type is ActionType.NOOP:
                    return MemoryAction(ActionType.NOOP)
                # UPDATE/DELETE need a target id the model text doesn't reliably
                # contain yet (prompt format doesn't ask for one) — fall back to
                # the most recent existing relation on the same subject/predicate.
                same_predicate = [r for r in existing if r.predicate == candidate.predicate]
                if not same_predicate:
                    continue
                target = same_predicate[0]
                if action_type is ActionType.DELETE:
                    return MemoryAction(ActionType.DELETE, target_id=target.id)
                return MemoryAction(
                    ActionType.UPDATE,
                    target_id=target.id,
                    updates={"object_id": candidate.object_id, "provenance": candidate.provenance},
                )

        return MemoryAction(ActionType.NOOP)
