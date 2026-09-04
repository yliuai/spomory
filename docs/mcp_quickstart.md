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

### ⚠️ macOS 上不要把运行时装在 `~/Documents`（或 Desktop/Downloads）下

**真实踩过的坑**：如果 `command` 指向 `~/Documents/<project>/.venv/...`，
Claude Desktop 启动 MCP Server 子进程时会报 `Server disconnected`，日志
（`~/Library/Logs/Claude/mcp-server-<name>.log`）里能看到：

```
Fatal Python error: init_import_site: Failed to import the site module
...
PermissionError: [Errno 1] Operation not permitted: '.../.venv/pyvenv.cfg'
```

根因是 macOS 的 TCC（隐私保护）机制：`~/Documents`、`~/Desktop`、
`~/Downloads` 这几个文件夹默认对没有被显式授权"完全磁盘访问权限"的
App 及其子进程是保护起来的，Claude Desktop spawn 出的 MCP Server 进程
拿不到这个授权，连 Python 启动时读自己 venv 目录下的 `pyvenv.cfg` 都会被
拒绝——**这和代码本身、和项目仓库放哪里没关系，纯粹是这几个特殊文件夹
的系统级限制**。

**解决办法**：把 MCP Server 实际运行用的虚拟环境装在 `~/Documents`
之外的普通目录（比如 `~/mcp-servers/`），用**非 editable**方式安装
（这样运行时不需要再回头读项目仓库里的源码）：

```bash
mkdir -p ~/mcp-servers
uv venv --python 3.11 ~/mcp-servers/memory-core-venv
uv pip install "/path/to/memory-core[llm,embedding,mcp]" \
    --python ~/mcp-servers/memory-core-venv/bin/python
```

项目仓库本身（源码开发）留在哪里都无所谓，只有**这个专门给 Claude
Desktop 用的运行时副本**需要挪到 `~/Documents` 之外。以后改了代码想让
Claude Desktop 用上最新版本，重新跑一遍上面这条 `uv pip install` 命令
（不带 `-e`）覆盖安装即可。

### 配置

在 `claude_desktop_config.json`（macOS 路径：
`~/Library/Application Support/Claude/claude_desktop_config.json`；
Cursor 用它的等价 MCP 配置文件）里加一段。`command` 写上面那个**非
Documents 路径**虚拟环境里 `memory-core-mcp` 的绝对路径——Claude Desktop
启动子进程时也不一定继承你终端的 `PATH`，绝对路径最不容易出问题：

```json
{
  "mcpServers": {
    "memory-core": {
      "command": "/Users/<you>/mcp-servers/memory-core-venv/bin/memory-core-mcp",
      "env": {
        "LLM_API_KEY": "...",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-v4-flash"
      }
    }
  }
}
```

如果这个 JSON 文件里已经有别的键（比如 Claude Desktop 自己的其他偏好
设置），只在顶层加 `mcpServers` 这一个键，不要动其他内容——改之前建议
先复制一份备份。改完配置后完全退出并重新打开 Claude Desktop 才会生效。

### 数据文件存放位置

本地 SQLite 数据文件（图谱数据 + 用量统计）默认存在 `~/.memory-core/`
（`MEMORY_CORE_DATA_DIR` 环境变量可以改)——这也是特意选的一个不在
Documents/Desktop/Downloads 下的普通目录，同样是为了避开上面那个 TCC
限制，而不是依赖进程启动时的当前工作目录（GUI App 拉起子进程时的 cwd
往往不可预测）。

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

**排查方法**：如果 Claude Desktop 提示 "Server disconnected"，真实的报错
（不是那句笼统的断连提示）在 `~/Library/Logs/Claude/mcp-server-memory-core.log`
里——先看这个文件，上面那个 TCC 权限问题就是从这里诊断出来的。

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
