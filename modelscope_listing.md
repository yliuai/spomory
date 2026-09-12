**中文 | [English](modelscope_listing.en.md)**

## Spomory

Spomory 是一个可解释的图检索记忆引擎，通过 MCP 协议为 Claude Desktop、Cursor 等客户端提供长期记忆能力。

**核心技术路线**：HippoRAG 式检索（查询→三元组匹配 + 个性化 PageRank 扩散）+ LightRAG 式增量知识图谱（只处理新增文本，不重建整图）+ GRPO 训练的记忆管理策略——不是硬编码的增删规则，而是训练出来判断该"记/忘/更新"的决策模型。

**提供 5 个 MCP 工具**：
- `add_memory` — 从文本抽取事实并写入记忆图谱
- `search_memory` — 通过图谱遍历检索并组装相关上下文
- `forget_memory` — 真删除单条匹配到的事实（不是软删除标记）
- `get_graph` — 查看某实体周围的关系子图，每条检索结果都能追溯到具体三元组，不只是一个相似度分数
- `export_memory` — 导出完整记忆图谱为 JSON"记忆护照"

**部署方式**：支持本地部署（数据完全留在本机 SQLite，默认加密）和远程托管（多租户 Postgres，支持 API Key 和 OAuth 2.1 两种鉴权方式）。

LoCoMo/LongMemEval 基准测试的实测结果和局限性说明公开在 [GitHub README](https://github.com/yliuai/spomory) 中。
