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


def _client_identity(relation: Relation) -> tuple[str | None, str | None]:
    if not relation.provenance:
        return None, None
    last = relation.provenance[-1]
    return last.client_name, last.session_id


def _is_cross_client_conflict(candidate: Relation, outdated: Relation) -> bool:
    """True when `candidate` and `outdated` can be *confirmed* to have come
    from different MCP connections -- either a different declared client, or
    the same declared client but a different connection-scoped session id
    (two windows of the same app on one machine report an identical
    client_name but distinct session ids on the remote/streamable-http
    path -- a real gap in an earlier version of this check, which only
    compared client_name).

    Conservative by construction: whenever a signal needed to tell them
    apart is missing on either side, this returns False and the existing
    update-in-place behavior applies. Unconfirmed is never treated as
    confirmed-different -- a false NOOP-to-UPDATE costs a kept-but-outdated
    fact next to a correction; a false ADD-as-conflict costs a spurious
    duplicate every ordinary correction never actually needed.
    """
    candidate_name, candidate_session = _client_identity(candidate)
    outdated_name, outdated_session = _client_identity(outdated)

    if not candidate_name or not outdated_name:
        return False
    if candidate_name != outdated_name:
        return True
    return bool(candidate_session and outdated_session and candidate_session != outdated_session)


class RuleBasedPolicy(MemoryPolicy):
    """Heuristic baseline: ADD anything new; if a relation already exists with
    the same subject+predicate but a different object, UPDATE it (the fact
    changed — e.g. a new job replaces an old one); otherwise NOOP on exact
    duplicates. Never DELETEs on its own (no rule can safely infer "this is
    now false" from one new sentence) — that's exactly the gap Epic 3's GRPO
    policy is meant to fill in over this baseline.

    The UPDATE branch is a real limitation, not just a simplification: it
    always treats the *incoming* candidate as correct, with no comparison of
    timestamps, confidence, or anything else -- there's nothing here that
    makes the newer one right. The one case this does guard against:
    `_is_cross_client_conflict()` -- when the existing and incoming relation
    can be *confirmed* to have come from different MCP connections (either a
    different declared client, or the same declared client but a different
    connection-scoped session id -- two windows of the same app on one
    machine share a client_name but not a session_id), this isn't "the same
    session correcting itself," it's two connections disagreeing -- and
    picking a winner there would be a pure guess. So that specific case
    keeps both relations (ADD) and flags the conflict via
    MemoryAction.conflict_with, instead of silently overwriting. Identity is
    unverified for a same-client-same-session update or when a needed signal
    is missing on either side (older clients, local stdio's session_id,
    missing handshake info) -- that ambiguous majority of cases still falls
    through to the unconditional UPDATE below.
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
            # Epic 12.1: exact duplicate -- NOOP carries the existing
            # relation's id so apply_action can bump its mention_count.
            return MemoryAction(ActionType.NOOP, target_id=same.id)

        outdated = existing[0]

        if _is_cross_client_conflict(candidate, outdated):
            return MemoryAction(ActionType.ADD, relation=candidate, conflict_with=outdated.id)

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
            # Epic 12.1: adopting a duplicate bumps mention_count rather
            # than being a true no-op (see RuleBasedPolicy above).
            return MemoryAction(ActionType.NOOP, target_id=same.id)
        outdated = existing[0]
        if _is_cross_client_conflict(candidate, outdated):
            return MemoryAction(ActionType.ADD, relation=candidate, conflict_with=outdated.id)

        return MemoryAction(
            ActionType.UPDATE,
            target_id=outdated.id,
            updates={"object_id": candidate.object_id, "provenance": candidate.provenance},
        )
