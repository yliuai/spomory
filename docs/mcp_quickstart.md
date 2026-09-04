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

**存储后端**（Epic 8.2）：不设置 `DATABASE_URL` 时默认用本地 SQLite
（`memory_core.sqlite3`）；设置了就自动切换到 Postgres 云端后端
（`memory_core/mcp_server/server.py::_select_store_from_env()`），接口行为
完全一致，已用 `tests/test_postgres_mcp_parity.py` 验证过：

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # 可选
```

## 启动

```bash
memory-core-mcp
```

## 接入 Claude Desktop / Cursor

在 `claude_desktop_config.json`（macOS 路径：
`~/Library/Application Support/Claude/claude_desktop_config.json`；
Cursor 用它的等价 MCP 配置文件）里加一段。`command` 建议写虚拟环境里
`memory-core-mcp` 的**绝对路径**——Claude Desktop 启动子进程时不一定继承你
终端的 `PATH`，写绝对路径最不容易出问题：

```json
{
  "mcpServers": {
    "memory-core": {
      "command": "/path/to/memory-core/.venv/bin/memory-core-mcp",
      "env": {
        "LLM_API_KEY": "...",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-v4-flash"
      }
    }
  }
}
```

把 `/path/to/memory-core` 换成你本机 clone/安装这个项目的实际路径（先跑过
`uv venv --python 3.11 .venv && uv pip install -e ".[llm,embedding,mcp]"`，
确保 `.venv/bin/memory-core-mcp` 这个文件存在）。改完配置后完全退出并重新
打开 Claude Desktop 才会生效。

**验证步骤**（照着做一遍，10 分钟内应该能跑通）：

1. 打开 Claude Desktop，新建对话，确认输入框附近能看到 MCP 工具图标／
   `memory-core` 已连接（没连上通常是 `command` 路径写错，或者环境变量里
   `LLM_API_KEY` 没填）。
2. 让 Claude 调用 `add_memory` 写入一句话，比如"记住：我在某某公司做后端
   开发"。
3. 开一个新对话（或者接着问），让 Claude 调用 `search_memory` 查"我在哪里
   工作"，确认能检索到第 2 步写入的内容。
4. 如果想验证云端后端（Epic 8.2），把 `env` 里加一条 `DATABASE_URL`
   指向 Postgres，重启 Claude Desktop，重复第 2-3 步，确认行为一致。

## 验证状态

- **代码 + 单元测试**：已完成。`tests/test_mcp_server.py` 用官方 `mcp` SDK
  （v2，`MCPServer`）的 `list_tools()` 验证四个工具都正确注册；`server.py`
  的检索/写入逻辑复用了已经用真实 LLM+embedding 验证过的 Epic 1/2 pipeline
  （见 `tests/test_e2e_real_llm.py`），存储后端在本地 SQLite 和云端 Postgres
  之间的切换也做了功能对等性验证（`tests/test_postgres_mcp_parity.py`）。
- **Epic 6.2 要求的"连接 Claude Desktop/Cursor 做真实端到端验证"**：这一步
  需要本地图形界面的桌面客户端环境，没法从这台开发/训练服务器上执行——按
  上面"验证步骤"在你自己装了 Claude Desktop 的机器上跑一遍，结果如实反馈
  即可，跑完这一步 Epic 6.2 就算完整验收。
