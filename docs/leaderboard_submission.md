# Epic 4.5：第三方排行榜调研

## 结论：Agent Memory Leaderboard 目前仍在维护，但本仓库现阶段无法提交

调研时间：2026-09-03。

## 现状（真实调研结果，非猜测）

方案里提到的 Agent Memory Leaderboard（AML）**仍在积极维护**：

- 由 20+ 所高校/研究机构在 2026 年 7 月 29 日发起，"Agent Memory
  Challenge 2026" 正在进行中，同时接受开源和商业记忆系统提交。
- 第一轮已审核 136+ 个记忆系统，8 月 12 日公布结果；第一轮提交截止日期
  是 2026 年 8 月 7 日（本仓库这轮已经错过）。
- **第二轮预计 2026 年 9 月 20 日开放**，之后会持续接受新系统提交。
- 官网：`agentmemoryleaderboard.ai`；仓库：`AML-memory/agent-memory-leaderboard`。

## 提交要求

1. 系统必须暴露公开可访问的 **Add** 和 **Search** 两个接口（HTTP API）——
   平台自己控制答案生成、评测、打分和跑批流程，参赛方只负责"记忆"这一层。
2. 走 `agentmemoryleaderboard.ai/evaluation` 申请评测资格，拿到 AML Key
   后先跑兼容性冒烟测试，再跑完整评测套件。
3. 分开源、商业两个类别：开源类要求公开代码、配置、可复现材料。
4. 结果 0-100 分制，评测完成前保持私密，通过 review 后才上榜。

## 为什么现阶段还提交不了

对照要求逐条看，本仓库目前缺的是：

- **没有公开可访问的 Add/Search HTTP 接口**——现在只有本地 MCP Server
  （stdio 协议，走 Claude Desktop/Cursor），不是 AML 要求的公开 HTTP
  服务。这是 Epic 8（云端 FastAPI 服务）的范畴，Epic 8.1 只搭了认证/配额
  骨架，还没有把 Epic 1/2 的记忆读写能力包装成公开 API 端点。
- **Epic 4.2 要求的完整 pipeline 正式跑分还没做**——目前只有 Epic 4.3
  记录的一个 6 条问答对小子集结果（见 `docs/benchmark_smoke_test.md`），
  远达不到"跑通 100+ 样本、可发表"的正式基准要求。

## 下一步（可执行的行动项，不是空泛建议）

1. 在 Epic 8.1 的 FastAPI 骨架上补两个端点：`POST /memory/add`、
   `POST /memory/search`，直接复用 `IncrementalIngestor` 和
   `retrieval/` 里已经跑通、有真实 LLM 验证过的逻辑——工作量不大，
   核心算法都已经现成。
2. 把这两个端点部署到一个公网可访问的地址（本仓库目前没有云端部署，
   这一步需要实际的服务器/托管环境）。
3. 补完 Epic 4.2 的正式跑分（100+ 样本、真实指标），作为提交前的
   内部基线参照。
4. 赶在 2026 年 9 月 20 日第二轮开放窗口，走 `agentmemoryleaderboard.ai/evaluation`
   申请评测资格。

## 如果最终没赶上榜单窗口的替代可信度背书方式

方案里已经规划了替代路径（不依赖这一个榜单）：把 4.1/4.2 的方法论和结果
整理成技术博客/预印本（Epic 4.4）、开源仓库本身保持可复现（README + 详细
测试覆盖），这两条不依赖 AML 是否按时开放第二轮。
