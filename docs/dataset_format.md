# Epic 3.1 训练数据格式

## 数据来源

用的是公开的 LoCoMo-10 数据集（`snap-research/locomo`，与 2402.17753 论文对应的
官方发布），而不是自行标注 150 条——数据集本身已经包含 10 段多轮对话
（每段跨多个 session、数月时间跨度）+ 约 2000 条带证据链接（`evidence`，指向具体
`dia_id`）的问答对，比自行标注更省时间也更权威。

获取方式：

```
python benchmarks/download_data.py
```

会把 `locomo10.json` 存到 `benchmarks/data/`（该目录已加入 `.gitignore`，
不提交进仓库——按标准实践，公开数据集用脚本拉取，不把 2.8MB 的原始 JSON
放进代码仓库）。解析逻辑见 `benchmarks/loaders.py::load_locomo()`。

## 原始字段

每段对话（`Conversation`）包含：

- `turns: list[DialogueTurn]`——按 session 顺序展开的全部对话轮次，
  每条有 `turn_id`（如 `"D1:3"`）、`speaker`、`text`。
- `qa_pairs: list[QAPair]`——每条有 `question`、`answer`、
  `evidence_turn_ids`（该问题的答案在哪些 `turn_id` 里能找到依据）、
  `category`（LoCoMo 的问题类型编号；`category == 5` 是对抗性/不可回答问题，
  这类问题没有真实 `answer` 字段，`loaders.py` 会 fallback 到
  `adversarial_answer`）。

## TASKS.md Epic 3.1 要求的训练样本格式：已用真实 LLM 生成，但规模不到 150 条

`(对话历史, 候选记忆操作, 下游问答是否正确)`。生成流程（对应脚本已跑通，
不是伪代码）：

1. 对每个 `turn` 调用 `IncrementalIngestor.ingest()`（真实 DeepSeek API），
   抽取候选三元组。
2. 对每个 `qa_pair`，跑检索+生成流程，用 LLM 语义评判
   （`benchmarks/harness.py::make_llm_judge_scorer`）判断 `predicted_answer`
   是否命中 `answer`。
3. 把每个"有候选三元组抽取结果 + 至少被一个下游问答引用为证据"的 turn，
   按 (对话文本, 候选ADD操作描述, 该 turn 关联问答是否被答对) 的形状落盘
   成 JSONL 一行。

## 实际产出：27 条真实标注样本，未达到建议的 ~150 条

`benchmarks/data/memory_ops_train.jsonl`（16 条，LoCoMo conv-30 前40轮）+
`benchmarks/data/memory_ops_train_conv3.jsonl`（11 条，LoCoMo conv-41 前70轮）
+ 两者合并后的 `benchmarks/data/memory_ops_train_merged.jsonl`（27 条，
Epic 3.4 训练实际用的是这个文件）——全部是真实 LLM 调用生成的真实数据，
不是占位/合成数据。

**没有达到 150 条的诚实原因**：不是每一轮对话都会被后续问答引用为证据
——70 轮对话平均只产出约 11-16 条能配上"下游问答结果"标签的样本，产出率
大概是 15-25%。要凑够 150 条，按这个产出率大约需要处理 700-1000 轮对话，
在这台开发环境到 LLM API 的网络延迟下（单次调用 5-90 秒不等），预计需要
再投入数小时的真实调用时间。`docs/memory_manager_eval.md` 记录了这个数据
规模不足对 GRPO 训练实际造成的影响（组内奖励方差为 0，没有真实梯度）。
