# MCP Server 快速开始

对应 TASKS.md Epic 6.2-6.4。`memory-core` 的 MCP Server 暴露四个工具：
`add_memory`、`search_memory`、`get_graph`、`export_memory`（见
`src/memory_core/mcp_server/server.py`），默认用本地 `LocalGraphStore`
（SQLite 文件 `memory_core.sqlite3`）。

## 安装

```bash
uv pip install "memory-core[llm,embedding,mcp] @ git+https://github.com/<org>/<repo>.git"
# 或本地开发：
uv pip install -e ".[llm,embedding,mcp]"
```

## 配置

设置以下环境变量（默认走 OpenAI；国产 OpenAI 兼容 API 只需换
`LLM_BASE_URL`/`LLM_MODEL`）：

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://api.deepseek.com   # 可选，默认 OpenAI
export LLM_MODEL=deepseek-v4-flash             # 可选，默认 gpt-4o-mini
export EMBEDDING_MODEL=BAAI/bge-m3             # 可选，默认 bge-m3
```

## 启动

```bash
memory-core-mcp
```

## 接入 Claude Desktop / Cursor

在 `claude_desktop_config.json`（或 Cursor 的等价 MCP 配置文件）里加：

```json
{
  "mcpServers": {
    "memory-core": {
      "command": "memory-core-mcp",
      "env": {
        "LLM_API_KEY": "...",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-v4-flash"
      }
    }
  }
}
```

## 验证状态

- **代码 + 单元测试**：已完成。`tests/test_mcp_server.py` 用官方 `mcp` SDK
  的 `FastMCP.list_tools()` 验证四个工具都正确注册；`server.py` 的检索/写入
  逻辑复用了已经用真实 LLM+embedding 验证过的 Epic 1/2 pipeline
  （见 `tests/test_e2e_real_llm.py`）。
- **Epic 6.2 要求的"连接 Claude Desktop/Cursor 做真实端到端验证"**：这一步
  需要本地图形界面的桌面客户端环境，在当前开发环境里无法执行——本文档记录了
  接入步骤，实际连接验证需要在装有 Claude Desktop 或 Cursor 的机器上手动跑一遍。
