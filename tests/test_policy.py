import pytest

from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Provenance, Relation
from memory_core.memory_manager.actions import ActionType
from memory_core.memory_manager.policy import RuleBasedPolicy


def _store_with(tmp_path, existing_relation: Relation | None, a: Entity, b: Entity):
    store = LocalGraphStore(tmp_path / "g.sqlite3")
    store.add_entities([a, b])
    if existing_relation is not None:
        store.add_relations([existing_relation])
    return store


def test_rule_based_adds_new_fact(tmp_path):
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store = _store_with(tmp_path, None, a, b)
    candidate = Relation(subject_id=a.id, predicate="任职于", object_id=b.id)

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.ADD
    assert action.relation == candidate


def test_rule_based_noops_on_exact_duplicate(tmp_path):
    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    existing = Relation(subject_id=a.id, predicate="任职于", object_id=b.id)
    store = _store_with(tmp_path, existing, a, b)
    candidate = Relation(subject_id=a.id, predicate="任职于", object_id=b.id)

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.NOOP
    assert action.target_id == existing.id  # Epic 12.1: so apply_action can bump mention_count


def test_rule_based_updates_when_object_changes(tmp_path):
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(subject_id=a.id, predicate="任职于", object_id=b.id)
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(subject_id=a.id, predicate="任职于", object_id=c.id)

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.UPDATE
    assert action.target_id == existing.id
    assert action.updates["object_id"] == c.id


def _provenance(client_name: str | None, session_id: str | None = None) -> Provenance:
    return Provenance(source_id="s", source_span="span", client_name=client_name, session_id=session_id)


def test_rule_based_keeps_both_on_cross_client_conflict(tmp_path):
    """The failure mode a real reviewer called out: two clients writing
    contradicting facts, with nothing in a memory graph making the newer one
    right. When both sides declare a *different* MCP client, decide() must
    not silently pick a winner."""
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(
        subject_id=a.id, predicate="任职于", object_id=b.id, provenance=[_provenance("claude-ai")]
    )
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(
        subject_id=a.id, predicate="任职于", object_id=c.id, provenance=[_provenance("cursor")]
    )

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.ADD
    assert action.relation == candidate
    assert action.conflict_with == existing.id


def test_rule_based_still_updates_on_same_client_correction(tmp_path):
    """Same client, same session correcting itself -- the ambiguous-but-
    probably-fine case -- keeps the existing unconditional-UPDATE behavior."""
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(
        subject_id=a.id, predicate="任职于", object_id=b.id, provenance=[_provenance("claude-ai")]
    )
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(
        subject_id=a.id, predicate="任职于", object_id=c.id, provenance=[_provenance("claude-ai")]
    )

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.UPDATE
    assert action.conflict_with is None


def test_rule_based_updates_when_client_identity_is_unknown(tmp_path):
    """Neither side declaring a client (the common case today, since most
    callers don't pass clientInfo through) can't be told apart from a
    same-client correction -- falls through to the existing UPDATE behavior
    rather than assuming a conflict that can't actually be confirmed."""
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(subject_id=a.id, predicate="任职于", object_id=b.id)  # no provenance at all
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(subject_id=a.id, predicate="任职于", object_id=c.id)

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.UPDATE
    assert action.conflict_with is None


def test_rule_based_treats_two_windows_of_the_same_app_as_a_conflict(tmp_path):
    """A real gap a reviewer caught in the client_name-only check: client_name
    identifies the *application* ('claude-ai'), not a specific window/
    connection of it -- two Claude Desktop windows on the same machine
    report an identical client_name. Distinct session_id on an identical
    client_name must still be recognized as a genuine conflict, not waved
    through as a same-session correction."""
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(
        subject_id=a.id,
        predicate="任职于",
        object_id=b.id,
        provenance=[_provenance("claude-ai", session_id="window-1")],
    )
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(
        subject_id=a.id,
        predicate="任职于",
        object_id=c.id,
        provenance=[_provenance("claude-ai", session_id="window-2")],
    )

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.ADD
    assert action.conflict_with == existing.id


def test_rule_based_updates_when_session_id_also_matches(tmp_path):
    """Same client, same connection -- session_id confirms it's genuinely
    the same session, not just an unlabeled one. Still an update-in-place."""
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(
        subject_id=a.id,
        predicate="任职于",
        object_id=b.id,
        provenance=[_provenance("claude-ai", session_id="window-1")],
    )
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(
        subject_id=a.id,
        predicate="任职于",
        object_id=c.id,
        provenance=[_provenance("claude-ai", session_id="window-1")],
    )

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.UPDATE
    assert action.conflict_with is None


def test_rule_based_updates_when_session_id_is_unavailable_on_either_side(tmp_path):
    """Local stdio deployments never populate session_id -- same client_name
    with no session_id on either side must not be treated as a confirmed
    conflict just because the values happen to differ from None to None
    (or one side has it and the other doesn't); missing is missing, and an
    unconfirmed signal falls through to the existing update behavior."""
    a, b, c = (Entity(name=n, type="thing") for n in "abc")
    existing = Relation(
        subject_id=a.id, predicate="任职于", object_id=b.id, provenance=[_provenance("claude-ai")]
    )
    store = _store_with(tmp_path, existing, a, b)
    store.add_entities([c])
    candidate = Relation(
        subject_id=a.id,
        predicate="任职于",
        object_id=c.id,
        provenance=[_provenance("claude-ai", session_id="window-1")],
    )

    action = RuleBasedPolicy().decide(candidate, store)

    assert action.action_type is ActionType.UPDATE
    assert action.conflict_with is None


@pytest.mark.slow
def test_trained_policy_loads_checkpoint_and_decides(tmp_path):
    pytest.importorskip("trl")
    pytest.importorskip("peft")

    from memory_core.memory_manager.train_grpo import build_trainer, load_dataset

    dataset_path = tmp_path / "episodes.jsonl"
    dataset_path.write_text(
        '{"prompt": "候选操作：ADD(a,任职于,b)。是否采纳？", "qa_correct": true}\n'
        '{"prompt": "候选操作：ADD(c,聊到,天气)。是否采纳？", "qa_correct": false}\n'
    )
    checkpoint_dir = tmp_path / "checkpoint"
    trainer = build_trainer(
        "hf-internal-testing/tiny-random-LlamaForCausalLM", load_dataset(dataset_path), str(checkpoint_dir)
    )
    trainer.train()
    trainer.save_model(str(checkpoint_dir))

    from memory_core.memory_manager.policy import TrainedPolicy

    a, b = Entity(name="a", type="thing"), Entity(name="b", type="thing")
    store = _store_with(tmp_path, None, a, b)
    candidate = Relation(subject_id=a.id, predicate="任职于", object_id=b.id)

    policy = TrainedPolicy(str(checkpoint_dir))
    action = policy.decide(candidate, store)

    assert action.action_type in set(ActionType)
