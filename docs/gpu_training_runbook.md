# GPU 到手后：跑通 Epic 3.4-3.6 的操作手册

`memory_manager/train_grpo.py` 的 TRL/PEFT 训练链路已经用占位小模型
（`hf-internal-testing/tiny-random-LlamaForCausalLM`）跑通并有单元测试
（`tests/test_train_grpo.py`）——数据加载、LoRA 配置、`GRPOTrainer.train()`
完整跑一轮、奖励/loss 有真实输出，这些都验证过了。拿到 GPU 访问后，只需要
换成真实模型和真实数据，不需要改代码逻辑。

## 前置：数据集

`benchmarks/data/memory_ops_train.jsonl`——本次会话已经用真实 LLM
（DeepSeek）在 LoCoMo 第 2 段对话上跑出了一批真实标注样本（而非占位数据），
字段说明见 `docs/dataset_format.md`。如果需要更大规模（更接近 Epic 3.1
建议的 150 条），可以对更多段 LoCoMo 对话重复跑
`benchmarks/harness.py` 同款流程。

## 需要你提供的

1. GPU 机器的访问方式（SSH/Jupyter/云平台 CLI 均可），确认已装好
   CUDA + PyTorch（`trl`/`peft`/`transformers` 会在 `uv pip install -e ".[rl]"`
   时自动装好，不需要你手动配置这几个包）。
2. 确认基座模型：默认 `Qwen/Qwen2.5-7B-Instruct`（方案里点名的选择），
   如果你有别的偏好或者机器显存有限需要换更小的模型，告诉我。

## 跑起来的命令

```bash
uv pip install -e ".[rl]"
python -m memory_core.memory_manager.train_grpo \
    --base-model Qwen/Qwen2.5-7B-Instruct \
    --dataset benchmarks/data/memory_ops_train.jsonl \
    --output-dir checkpoints/memory-grpo-lora
```

## 训练完之后

1. `memory_manager/policy.py` 的 `TrainedPolicy` 已经能加载 PEFT checkpoint
   做推理（`tests/test_policy.py::test_trained_policy_loads_checkpoint_and_decides`
   已经用占位模型验证过加载+推理链路能跑通），换成真实 checkpoint 路径即可：
   ```python
   policy = TrainedPolicy("checkpoints/memory-grpo-lora")
   ```
2. Epic 3.6 的对比评估：在 `benchmarks/data/memory_ops_train.jsonl` 的验证集
   （或另外切一部分 LoCoMo 数据）上，分别跑 `RuleBasedPolicy` 和训练后的
   `TrainedPolicy`，对比下游 QA 准确率，写进 `docs/memory_manager_eval.md`
   （如实记录，哪怕没有显著提升）。
