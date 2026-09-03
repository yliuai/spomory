import pytest

from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.models import Entity, Relation
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
