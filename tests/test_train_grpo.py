"""Epic 3.4: smoke-test the GRPO training script's plumbing.

This does NOT verify that training improves the policy on real data — that
needs the real ~150-episode dataset and a real 7-8B base model on a GPU
box, neither available here. It verifies the TRL/PEFT wiring itself is
correct end to end (dataset -> LoRA config -> GRPOTrainer.train() completing
without error and reporting a real reward/loss) against a tiny placeholder
model, which is the part that's actually verifiable in this environment.
"""

import pytest

pytest.importorskip("trl")
pytest.importorskip("peft")

TINY_MODEL = "hf-internal-testing/tiny-random-LlamaForCausalLM"


def test_completion_adopts_the_action_parses_yes_and_no():
    from memory_core.memory_manager.train_grpo import _completion_adopts_the_action

    assert _completion_adopts_the_action("是的，应该采纳这个操作。") is True
    assert _completion_adopts_the_action("不应该采纳，这条信息不重要。") is False
    assert _completion_adopts_the_action("") is False  # ambiguous -> conservative default


def test_reward_fn_varies_per_completion_not_just_per_prompt():
    """The bug this guards against: a reward function that ignores what each
    sampled completion actually said (and just echoes a per-prompt label)
    gives every completion in a GRPO group identical reward, which makes the
    within-group advantage -- and the gradient -- zero forever, regardless
    of dataset size. This was caught by real training runs showing
    grad_norm=0 even as the dataset grew from 16 to 27 real episodes.
    """
    from memory_core.memory_manager.train_grpo import _reward_fn

    completions = ["应该采纳", "不应该采纳", "应该采纳", "不应该采纳"]
    qa_correct = [True, True, False, False]  # same prompt/label repeated across the group

    rewards = _reward_fn(completions, qa_correct=qa_correct)

    assert len(set(rewards)) > 1, "reward must depend on the completion, not be constant"
    assert rewards[0] == 1.0  # adopted=True, correct=True -> match
    assert rewards[1] == 0.0  # adopted=False, correct=True -> mismatch
    assert rewards[2] == 0.0  # adopted=True, correct=False -> mismatch
    assert rewards[3] == 1.0  # adopted=False, correct=False -> match


@pytest.mark.slow
def test_grpo_trainer_wiring_runs_end_to_end(tmp_path):
    from memory_core.memory_manager.train_grpo import build_trainer, load_dataset

    dataset_path = tmp_path / "episodes.jsonl"
    dataset_path.write_text(
        '{"prompt": "候选操作：ADD(张三,任职于,某公司)。是否采纳？", "qa_correct": true}\n'
        '{"prompt": "候选操作：ADD(用户,聊到,天气)。是否采纳？", "qa_correct": false}\n'
        '{"prompt": "候选操作：DELETE(王五,联系,旧同事)。是否采纳？", "qa_correct": true}\n'
        '{"prompt": "候选操作：UPDATE(李四,居住地,新地址)。是否采纳？", "qa_correct": true}\n'
    )

    dataset = load_dataset(dataset_path)
    assert len(dataset) == 4

    trainer = build_trainer(TINY_MODEL, dataset, str(tmp_path / "out"))
    train_result = trainer.train()

    assert train_result is not None
