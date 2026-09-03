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

## TASKS.md Epic 3.1 要求的训练样本格式

`(对话历史, 候选记忆操作, 下游问答是否正确)`——这一层还需要在 LoCoMo 原始数据
之上再跑一遍完整 pipeline 才能生成：

1. 对每个 `turn` 调用 `IncrementalIngestor.ingest()`，产出该轮对话触发的
   候选记忆操作（ADD/UPDATE/DELETE/NOOP，对应 `memory_manager/actions.py`）。
2. 对每个 `qa_pair`，跑 `benchmarks/harness.py::run_conversation()` 的检索+生成
   流程，得到 `predicted_answer` 是否命中 `answer`（`CaseResult.correct`）。
3. 把 (1) 的操作序列和 (2) 的正确性对齐，按 `memory_manager/reward.py::Episode`
   的形状落盘成 JSONL。

第 1、2 步都依赖真实 LLM 调用（三元组抽取 + 问答生成），本仓库目前只有
`OpenAICompatibleProvider` 的代码和离线单元测试（用 `FakeLLMProvider` 走通
pipeline wiring），还没有配置真实 API Key 去跑一遍生成实际的 150+ 条标注样本
——这是 Epic 3.1 剩余的、需要外部资源（LLM API Key）才能完成的部分。
