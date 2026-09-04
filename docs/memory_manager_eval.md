# Epic 3.6：规则式 vs GRPO 训练后策略对比评估

如实记录：**这次真实训练没有产生有效的学习信号**，训练后的策略在决策质量
上不如规则式基线。这不是一次成功案例的报告，是按 Epic 3.6 的要求"哪怕
没有显著提升也如实记录"。

## 训练本身：跑通了，但没有学到东西

Epic 3.4 用真实 GPU（2×NVIDIA TITAN RTX 24GB）、真实 `Qwen/Qwen2.5-7B-Instruct`
基座模型、真实 TRL `GRPOTrainer` + PEFT LoRA，在 16 条真实标注样本
（`benchmarks/data/memory_ops_train.jsonl`，从 LoCoMo 对话用真实 LLM 抽取+
QA 验证生成）上跑完了 3 个 epoch（48 步），产出了一个真实的 LoRA
checkpoint（`checkpoints/memory-grpo-lora/`，20MB adapter）。训练脚本、
LoRA 配置、reward 接入全部按预期工作——**但训练日志里 `loss` 和 `grad_norm`
全程为 0**：

```
{'loss': '0', 'grad_norm': '0', ..., 'reward': '0.4', ...}
{'loss': '0', 'grad_norm': '0', ..., 'reward': '0.5', ...}
{'loss': '0', 'grad_norm': '0', ..., 'reward': '0.5', ...}
{'loss': '0', 'grad_norm': '0', ..., 'reward': '0.375', ...}
```

**根因**：GRPO 是组内相对优势估计——同一个 prompt 采样 `num_generations=4`
个 completion，靠组内奖励的方差算梯度。16 条样本、每条只采 4 个样本，
如果这 4 个采样结果奖励一致（`frac_reward_zero_std: 1`，日志显示每一步都
是这样），组内方差就是 0，梯度自然是 0——模型权重几乎没有更新。这是
**训练数据规模不足**导致的，不是代码或算法配置的问题。要让 GRPO 真正有
梯度信号，需要更大的数据规模（TASKS.md 建议的 ~150 条是一个更合理的起点）
和/或更高的采样温度制造组内多样性。

## 决策对比：3 个场景，真实 checkpoint vs 规则式基线

在同一个真实 checkpoint 上跑 `TrainedPolicy.decide()`，和 `RuleBasedPolicy`
对比三个手工构造但有明确"正确答案"的场景：

| 场景 | 期望动作 | `RuleBasedPolicy` | `TrainedPolicy`（训练后） |
|---|---|---|---|
| 全新事实（图中不存在同主体同谓语的关系） | ADD | ADD ✅ | ADD ✅ |
| 完全重复的事实（已存在一模一样的关系） | NOOP | NOOP ✅ | ADD ❌ |
| 冲突事实（同主体同谓语，宾语变了——比如换工作了） | UPDATE | UPDATE ✅ | NOOP ❌ |

`RuleBasedPolicy` 3/3 全对（它本来就是为这几种情况手写的启发式规则）。
`TrainedPolicy` 只在最简单的"全新事实"场景上和规则式一致，另外两个更需要
"结合已有记忆状态做判断"的场景都判断错误——这和上面"训练没有产生有效
梯度"的诊断是一致的：训练后的模型行为接近未经任务特定训练的基座模型的
默认倾向（倾向于无条件采纳新信息，而不是先比对已有记忆），而不是真正学会
了这个任务。

## 结论和下一步

按照当前的真实数据规模（16 条），GRPO 训练在流程上是完整可复现的，但
**不能得出"训练后策略优于规则式基线"的结论——真实证据指向相反方向**。
要得到有意义的对比结果，下一步必须先把 Epic 3.1 的数据集规模扩大到
TASKS.md 建议的量级（~150 条，理想情况下奖励在组内有真实方差），再重新
训练、重新跑这个对比。在那之前，生产环境应该继续用 `RuleBasedPolicy` 作为
默认动作选择逻辑，`TrainedPolicy` 保留代码路径但不作为默认——这也是
`memory_manager/policy.py` 当前的实际状态（两者都实现了，调用方需要显式
选择用哪个，没有偷偷把 `TrainedPolicy` 设成默认）。
