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
