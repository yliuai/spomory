# Spomory

**[English](README.md) | 中文**

个人 AI 记忆产品的核心引擎：HippoRAG 式检索（query→triple 匹配 + 个性化
PageRank 扩散）+ LightRAG 式双层增量知识图谱 + 轻量级 GRPO 记忆管理策略，
通过 MCP Server 接入 Claude Desktop / Cursor 等客户端，并预留了云端部署
（Postgres 后端、FastAPI 鉴权/计费骨架）的扩展路径。

> Spomory 是产品/客户端展示名；Python 包名、CLI 命令
> （`memory-core-mcp`）、代码里的模块名（`memory_core`）保持不变，见下方
> "快速开始：MCP Server"一节的说明。

## 已实现的能力

- **可插拔 LLM / Embedding 接口**：默认走任意 OpenAI 兼容 API（含国产模型）
  + 本地 `sentence-transformers`（默认 `bge-m3`，中英文混合）。
- **双层增量知识图谱**：实体层/关系层独立建模，新数据只做抽取+合并，不
  重建整图；默认本地 `LocalGraphStore`（networkx + SQLite），也有
  `PostgresGraphStore` 云端实现，两者共用同一套行为契约测试。
- **HippoRAG 2 式检索**：query 直接匹配三元组而非只匹配实体节点，检索到
  的种子节点做个性化 PageRank 扩散做多跳关联，再拼装成自然语言上下文
  （带来源时间戳，支持"我什么时候说过 X"这类问题）。
- **记忆管理**：ADD/UPDATE/DELETE/NOOP 动作空间，默认规则式策略
  （`RuleBasedPolicy`），也实现了 GRPO 训练策略的完整链路
  （`memory_manager/train_grpo.py`，真实在 GPU 上跑通过）。
- **MCP Server**：暴露 `add_memory`/`search_memory`/`get_graph`/
  `export_memory`/`forget_memory` 五个工具，真实在 Claude Desktop 里端到端验证过。
- **记忆护照导出 + 真删除**：JSON-LD 风格导出格式，物理删除 + 审计日志。
- **多模态图片验证**：图片 captioning → 复用文本抽取 → CLIP 二次校验候选
  三元组，诚实定位为"验证"而非"原生跨模态抽取"。
- **云端骨架**：FastAPI 用户认证/API Key/配额、Stripe webhook 计费雏形
  （均为骨架级实现，未做生产部署）。

## 项目结构

```
src/
├── memory_core/
│   ├── graph/            # 实体/关系模型、存储适配器（本地SQLite/云端Postgres）、增量写入
│   ├── retrieval/        # query→triple匹配、个性化PageRank、上下文拼装
│   ├── memory_manager/   # 动作空间、奖励函数、GRPO训练脚本、策略推理
│   ├── multimodal/       # 图片captioning + CLIP验证
│   ├── mcp_server/       # MCP Server（对外分发入口）
│   ├── export/           # 记忆护照导出格式与真删除
│   ├── llm/              # 可插拔 LLM/Embedding 接口
│   ├── audit.py          # 删除审计日志
│   └── usage.py          # 留存/使用埋点
└── cloud_api/            # FastAPI 云端服务骨架（认证、配额、计费）
benchmarks/                # LoCoMo/LongMemEval 评测 harness + 多模态对比实验
tests/                     # 94+ 个测试，覆盖单元测试到真实 LLM/GPU/Postgres 端到端验证
docs/                      # 各 Epic 的设计说明、验证报告、操作手册（见下方索引）
```

## 安装

前置要求：Python **3.11+**、[uv](https://docs.astral.sh/uv/getting-started/installation/)
（没有 uv 也可以用 `python -m venv` + `pip install -e` 替代下面的 `uv` 命令）。

```bash
git clone <本仓库地址> memory-core && cd memory-core
uv venv --python 3.11 .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 按需选择依赖组，可以叠加安装，不用一次装全部：
uv pip install -e ".[dev]"                 # 跑测试/lint 必需
uv pip install -e ".[llm,embedding]"       # 跑 “最小可用记忆系统” 必需（见下方 Demo）
uv pip install -e ".[mcp]"                 # 额外需要：接入 Claude Desktop/Cursor
uv pip install -e ".[rl]"                  # 额外需要：GRPO 训练（需要 GPU + CUDA）
uv pip install -e ".[cloud]"               # 额外需要：云端 API / Postgres 后端
uv pip install -e ".[multimodal]"          # 额外需要：图片 + CLIP 验证
```

`embedding` 这一组首次调用时会从 HuggingFace 下载默认模型 `BAAI/bge-m3`
（约 2.2GB），请确保网络可达 huggingface.co（国内可设置
`export HF_ENDPOINT=https://hf-mirror.com` 走镜像）。也可以用
`export EMBEDDING_MODEL=<其他 sentence-transformers 模型名>` 换成更小的模型。

`llm` 这一组本身不下载任何模型，但**运行时必须设置** `LLM_API_KEY`（任意
OpenAI 兼容的 Chat Completions 接口都可以，官方 OpenAI、DeepSeek、通义千问
等都行）：

```bash
export LLM_API_KEY=sk-...
export LLM_BASE_URL=https://api.deepseek.com   # 可选；不设默认是 OpenAI 官方地址
export LLM_MODEL=deepseek-chat                 # 可选；不设默认是 gpt-4o-mini
```

### 跑通一个最小例子（不依赖 MCP，纯 Python 调用）

装好 `dev` + `llm` + `embedding` 三组、设置好上面三个环境变量后，可以直接
用下面这段脚本验证"写入记忆 → 检索记忆"整条链路是否工作（对应
`mcp_server/server.py` 里 `add_memory`/`search_memory` 两个工具背后的真实
逻辑，只是这里绕开了 MCP 协议层，直接调库）：

```python
# demo.py
from memory_core.graph.local_store import LocalGraphStore
from memory_core.graph.incremental import IncrementalIngestor
from memory_core.llm.openai_compatible import OpenAICompatibleProvider
from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
from memory_core.memory_manager.policy import RuleBasedPolicy
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
from memory_core.retrieval.query_match import match_query_to_triples
from memory_core.retrieval.ranker import build_context

store = LocalGraphStore("demo.sqlite3")          # 本地文件，删掉即重置
llm = OpenAICompatibleProvider()                 # 读取 LLM_API_KEY 等环境变量
embedder = SentenceTransformerProvider()         # 首次运行会下载 bge-m3

# 1. 写入一条记忆：LLM 抽取三元组，增量合并进图谱
ingestor = IncrementalIngestor(store, llm, policy=RuleBasedPolicy())
result = ingestor.ingest("我在中科院做AI研究，主要用 Python。", source_id="demo")
print(f"新增实体 {result.new_entities} 个，新增关系 {result.new_relations} 条")

# 2. 检索：query 匹配三元组 -> PPR 扩散 -> 拼装自然语言上下文
query = "我在哪里工作？"
entities, relations = store.all_entities(), store.all_relations()
entities_by_id = {e.id: e for e in entities}
matches = match_query_to_triples(query, relations, entities_by_id, embedder, top_k=10)
seed_ids = {r.relation.subject_id for r in matches} | {r.relation.object_id for r in matches}
scores = personalized_pagerank(entities, relations, seed_entity_ids=list(seed_ids))
ranked_ids = [eid for eid, _ in rank_entities(scores)]
print(build_context(relations, entities_by_id, ranked_ids, top_k=10))
```

```bash
python demo.py
```

这是用 DeepSeek 真实跑出来的输出（下面这段不是编的，实测截图式记录）：

```
新增实体 4 个，新增关系 2 条
我在中科院做AI研究（记录于2026-09-04 22:36:00）。我主要用Python（记录于2026-09-04 22:36:00）。
```

具体措辞、实体/关系数量取决于所用 LLM 的抽取结果，每次跑不完全一致，
但只要环境变量配对了，跑出非空结果就说明链路是通的。

## 快速开始：MCP Server（接入 Claude Desktop / Cursor）

这个 MCP Server 在 Claude Desktop / Cursor 里显示的名字是 **Spomory**
（由客户端配置文件 `mcpServers` 下的键名决定，见下方文档）；Python 包名/
CLI 命令仍然是 `memory-core` / `memory-core-mcp`，两者是独立的。

装好 `mcp` 依赖组、设置好 `LLM_API_KEY` 等环境变量后：

```bash
uv pip install -e ".[llm,embedding,mcp]"
memory-core-mcp   # 启动后常驻，作为 stdio MCP server 等待客户端连接
```

数据默认落在 `~/.memory-core/`（可用 `MEMORY_CORE_DATA_DIR` 环境变量改变），
设置了 `DATABASE_URL` 则改用 Postgres 后端而非本地 SQLite。

把它接到 Claude Desktop / Cursor 需要在客户端配置文件里注册这个命令的**绝对
路径**（而不是指望 `PATH`），完整步骤、配置文件示例、以及一个真实踩过的坑
（macOS 上 TCC 隐私保护会拦截跑在 `~/Documents` 下的 venv，需要把 venv 装到
`~/Documents` 之外）见 [`docs/mcp_quickstart.md`](docs/mcp_quickstart.md)。

## 已验证效果

用真实 DeepSeek 在 LoCoMo-10（conv-26 前 150 轮，84 条问答对）上跑出来的
结果——不是精选的漂亮数字，目前也还比不过 Mem0/Perseus Vault 这些头部
玩家公开的数字：

| 指标 | 数值 |
|---|---|
| Recall@10（正确的证据轮次有没有进入上下文） | 52.4% |
| Accuracy — 严格子串匹配 | 19.0% |
| Accuracy — LLM 语义评判（措辞不同但语义正确也算对） | 44.0% |

修复前（把日期折叠进三元组谓语这个改动之前，"我什么时候说过X"这类问题
本来答不出来）准确率更低但 Recall@10 更高（62.0%）——这个修复用一部分
检索召回率换来了真实的 +14.3 个百分点准确率提升，而且没有止步于"准确率
变好了"就收工，而是去查清楚了 Recall 为什么会掉：日期折叠指令有时会
误触发在没有信息量的寒暄上（"谢谢！"被折成"在2023年7月3日道谢"），这些
额外的低价值三元组会挤占固定 `top_k=10` 检索窗口里真正相关三元组的名额。
完整数据、按问题类型的拆解、以及定位这个问题用的新旧抽取结果对比，都在
[`docs/benchmark_smoke_test.md`](docs/benchmark_smoke_test.md)。

## 测试

```bash
pytest                    # 全部测试
pytest -m "not slow"      # 跳过需要下载模型/训练的测试，几秒内跑完
```

多数"慢"测试不是 mock，而是真实调用（真实 LLM API、真实本地 embedding
模型、真实 CLIP 模型），需要相应的环境变量（`LLM_API_KEY` 等）或已下载的
模型缓存。

## 文档索引


| 文档                                                                                                                              | 内容                                                            |
| --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| [mcp_quickstart.md](docs/mcp_quickstart.md) ([English](docs/mcp_quickstart.en.md))                                                | MCP Server 安装、配置、接入 Claude Desktop/Cursor、真实踩坑记录 |
| [graph_store_interface.md](docs/graph_store_interface.md)                                                                         | 存储适配器接口设计说明                                          |
| [export_format.md](docs/export_format.md)                                                                                         | "记忆护照"导出格式                                              |
| [dataset_format.md](docs/dataset_format.md)                                                                                       | GRPO 训练数据格式与真实数据集生成过程                           |
| [methodology.md](docs/methodology.md)                                                                                             | 技术方法论：已验证结论 vs 尚待验证的部分                        |
| [benchmark_smoke_test.md](docs/benchmark_smoke_test.md)                                                                           | LoCoMo 真实跑分结果与失败案例分析                               |
| [memory_manager_eval.md](docs/memory_manager_eval.md)                                                                             | 规则式 vs GRPO 训练后策略对比，含调试过程                       |
| [multimodal_verification.md](docs/multimodal_verification.md)                                                                     | 图片 + CLIP 二次校验实验结果                                    |
| [gpu_training_runbook.md](docs/gpu_training_runbook.md)                                                                           | GPU 训练环境部署记录（含真实踩过的坑）                          |
| [postgres_setup.md](docs/postgres_setup.md)                                                                                       | 云端 Postgres 后端部署记录                                      |
| [leaderboard_submission.md](docs/leaderboard_submission.md)                                                                       | 第三方评测榜单调研                                              |
| [mvp_scope.md](docs/mvp_scope.md)                                                                                                 | MVP 最小功能范围定义                                            |
| [privacy_policy_draft.md](docs/privacy_policy_draft.md) / [product_copy_memory_passport.md](docs/product_copy_memory_passport.md) | 隐私政策草案 / 对外产品文案素材                                 |

## 已知限制

- 语音输入的多模态验证（ASR + 音频 embedding）尚未实现。
- GRPO 训练数据规模（140条真实样本）和训练步数仍偏小，`memory_manager_eval.md`
  如实记录了这个限制对训练效果的影响。
- 云端 API/计费仅为骨架实现，未接入真实生产环境。

## License

见 [LICENSE](LICENSE)。
