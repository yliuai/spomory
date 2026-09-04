# memory-core

个人 AI 记忆产品的核心引擎：HippoRAG 式检索（query→triple 匹配 + 个性化
PageRank 扩散）+ LightRAG 式双层增量知识图谱 + 轻量级 GRPO 记忆管理策略，
通过 MCP Server 接入 Claude Desktop / Cursor 等客户端，并预留了云端部署
（Postgres 后端、FastAPI 鉴权/计费骨架）的扩展路径。

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
  `export_memory` 四个工具，真实在 Claude Desktop 里端到端验证过。
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

```bash
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"                       # 基础开发环境
uv pip install -e ".[llm,embedding,mcp]"         # 跑 MCP Server 需要的最小集合
uv pip install -e ".[rl]"                        # GRPO 训练（需要 GPU）
uv pip install -e ".[cloud]"                     # 云端 API / Postgres 后端
uv pip install -e ".[multimodal]"                # 图片验证（CLIP）
```

各依赖组之间相互独立，按需安装即可，不需要一次性装全部。

## 快速开始：MCP Server

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://api.deepseek.com   # 可选，默认走 OpenAI
export LLM_MODEL=deepseek-v4-flash             # 可选
memory-core-mcp
```

接入 Claude Desktop / Cursor 的详细步骤（含 macOS 上一个真实踩过的坑：
运行时不能装在 `~/Documents` 下）见 [`docs/mcp_quickstart.md`](docs/mcp_quickstart.md)。

## 测试

```bash
pytest                    # 全部测试
pytest -m "not slow"      # 跳过需要下载模型/训练的测试，几秒内跑完
```

多数"慢"测试不是 mock，而是真实调用（真实 LLM API、真实本地 embedding
模型、真实 CLIP 模型），需要相应的环境变量（`LLM_API_KEY` 等）或已下载的
模型缓存。

## 文档索引

| 文档 | 内容 |
|---|---|
| [mcp_quickstart.md](docs/mcp_quickstart.md) | MCP Server 安装、配置、接入 Claude Desktop/Cursor、真实踩坑记录 |
| [graph_store_interface.md](docs/graph_store_interface.md) | 存储适配器接口设计说明 |
| [export_format.md](docs/export_format.md) | "记忆护照"导出格式 |
| [dataset_format.md](docs/dataset_format.md) | GRPO 训练数据格式与真实数据集生成过程 |
| [methodology.md](docs/methodology.md) | 技术方法论：已验证结论 vs 尚待验证的部分 |
| [benchmark_smoke_test.md](docs/benchmark_smoke_test.md) | LoCoMo 真实跑分结果与失败案例分析 |
| [memory_manager_eval.md](docs/memory_manager_eval.md) | 规则式 vs GRPO 训练后策略对比，含调试过程 |
| [multimodal_verification.md](docs/multimodal_verification.md) | 图片 + CLIP 二次校验实验结果 |
| [gpu_training_runbook.md](docs/gpu_training_runbook.md) | GPU 训练环境部署记录（含真实踩过的坑） |
| [postgres_setup.md](docs/postgres_setup.md) | 云端 Postgres 后端部署记录 |
| [leaderboard_submission.md](docs/leaderboard_submission.md) | 第三方评测榜单调研 |
| [mvp_scope.md](docs/mvp_scope.md) | MVP 最小功能范围定义 |
| [privacy_policy_draft.md](docs/privacy_policy_draft.md) / [product_copy_memory_passport.md](docs/product_copy_memory_passport.md) | 隐私政策草案 / 对外产品文案素材 |

## 已知限制

- 语音输入的多模态验证（ASR + 音频 embedding）尚未实现。
- GRPO 训练数据规模（140条真实样本）和训练步数仍偏小，`memory_manager_eval.md`
  如实记录了这个限制对训练效果的影响。
- 云端 API/计费仅为骨架实现，未接入真实生产环境。

## License

见 [LICENSE](LICENSE)。
