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
    ``train_grpo.py``.

    The model was only ever trained on one binary question — "should this
    candidate ADD be adopted?" (``train_grpo.py``'s
    ``_completion_adopts_the_action`` reward parser) — so that's the only
    thing this policy asks it at inference time too; the prompt here is
    built to match the training prompt shape exactly (an earlier version of
    this class asked a different, out-of-distribution "pick ADD/UPDATE/
    DELETE/NOOP" question the model was never trained to answer). Given an
    "adopt" answer, the structural ADD vs UPDATE vs NOOP decision reuses
    ``RuleBasedPolicy``'s logic (write the fact correctly); the model's own
    contribution is only the adopt/reject gate — it does not yet have a
    trained way to choose DELETE.
    """

    def __init__(self, checkpoint_dir: str, base_model: str | None = None) -> None:
        import torch
        from peft import AutoPeftModelForCausalLM
        from transformers import AutoTokenizer

        # Without an explicit device_map, a 7B model loads (and runs
        # generate()) entirely on CPU, ~10-100x slower than GPU. Match
        # train_grpo.py's device placement so this is actually usable.
        load_kwargs: dict[str, object] = {}
        if torch.cuda.is_available():
            load_kwargs["torch_dtype"] = torch.bfloat16
            load_kwargs["device_map"] = "auto"
        self.model = AutoPeftModelForCausalLM.from_pretrained(checkpoint_dir, **load_kwargs)
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)

    def _render_prompt(self, candidate: Relation) -> str:
        candidate_desc = f"({candidate.subject_id}, {candidate.predicate}, {candidate.object_id})"
        return f"候选操作：ADD {candidate_desc}\n是否应该采纳这个记忆操作？"

    def decide(self, candidate: Relation, store: GraphStoreBase) -> MemoryAction:
        from .train_grpo import _completion_adopts_the_action

        prompt = self._render_prompt(candidate)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        output_ids = self.model.generate(**inputs, max_new_tokens=16)
        decision_text = self.tokenizer.decode(
            output_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )

        if not _completion_adopts_the_action(decision_text):
            return MemoryAction(ActionType.NOOP)

        existing = [
            r
            for r in store.get_neighbors(candidate.subject_id)
            if r.subject_id == candidate.subject_id and r.predicate == candidate.predicate
        ]
        if not existing:
            return MemoryAction(ActionType.ADD, relation=candidate)
        same = next((r for r in existing if r.object_id == candidate.object_id), None)
        if same is not None:
            return MemoryAction(ActionType.NOOP)  # adopting a duplicate is a no-op either way
        outdated = existing[0]
        return MemoryAction(
            ActionType.UPDATE,
            target_id=outdated.id,
            updates={"object_id": candidate.object_id, "provenance": candidate.provenance},
        )
