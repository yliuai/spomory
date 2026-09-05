# MCP Server Quickstart

**English | [中文](mcp_quickstart.md)**

Covers TASKS.md Epic 6.2-6.4 (internal task tracker, not part of this
repo). This MCP server shows up in Claude Desktop / Cursor as **Spomory**
(`src/memory_core/mcp_server/server.py`'s `MCPServer("Spomory")`), and
exposes four tools: `add_memory`, `search_memory`, `get_graph`,
`export_memory`. It defaults to a local `LocalGraphStore` (SQLite file
`memory_core.sqlite3`).

> The Python package name, the CLI command (`memory-core-mcp`), and the
> module name in code are all still `memory_core` — only the **name
> registered with the client** was changed to Spomory. The two are
> independent: the `command` field points at whichever executable
> actually runs the code, while the key in the `mcpServers` JSON object is
> what shows up in the Claude Desktop/Cursor UI and names the log file
> (`mcp-server-<key>.log`). If you rename it, change both places, or the
> log filename and the displayed name will stop matching, which makes
> debugging confusing.

## Install

```bash
uv pip install "memory-core[llm,embedding,mcp] @ git+https://github.com/<org>/<repo>.git"
# or for local development:
uv pip install -e ".[llm,embedding,mcp]"
```

## Configure

Set the following environment variables (defaults to OpenAI; for a
Chinese-market OpenAI-compatible API, just swap `LLM_BASE_URL`/`LLM_MODEL`):

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://api.deepseek.com   # optional, defaults to OpenAI
export LLM_MODEL=deepseek-v4-flash             # optional, defaults to gpt-4o-mini
export EMBEDDING_MODEL=BAAI/bge-m3             # optional, defaults to bge-m3
```

**Storage backend** (Epic 8.2): with `DATABASE_URL` unset, it defaults to
local SQLite (`memory_core.sqlite3`); setting it switches automatically to
the Postgres cloud backend
(`memory_core/mcp_server/server.py::_select_store_from_env()`) with
identical behavior, verified by `tests/test_postgres_mcp_parity.py`:

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # optional
```

## Run

```bash
memory-core-mcp
```

## Connecting Claude Desktop / Cursor

### ⚠️ On macOS, don't install the runtime under `~/Documents` (or Desktop/Downloads)

**A real gotcha we actually hit**: if `command` points at
`~/Documents/<project>/.venv/...`, Claude Desktop's MCP Server subprocess
fails with `Server disconnected`, and the log
(`~/Library/Logs/Claude/mcp-server-<name>.log`) shows:

```
Fatal Python error: init_import_site: Failed to import the site module
...
PermissionError: [Errno 1] Operation not permitted: '.../.venv/pyvenv.cfg'
```

The root cause is macOS's TCC (privacy protection) mechanism:
`~/Documents`, `~/Desktop`, and `~/Downloads` are protected by default
against apps (and their subprocesses) that haven't been explicitly
granted "Full Disk Access." The MCP Server process Claude Desktop spawns
doesn't have that grant, so even Python reading its own venv's
`pyvenv.cfg` at startup gets denied — **this has nothing to do with the
code itself or where the repo lives; it's purely an OS-level restriction
on these specific folders**.

**The fix**: install the virtual environment actually used to run the MCP
Server somewhere outside `~/Documents` (e.g. `~/mcp-servers/`), installed
**non-editable** (so it doesn't need to read back into the repo's source
at runtime):

```bash
mkdir -p ~/mcp-servers
uv venv --python 3.11 ~/mcp-servers/memory-core-venv
uv pip install "/path/to/memory-core[llm,embedding,mcp]" \
    --python ~/mcp-servers/memory-core-venv/bin/python
```

The repo itself (for source development) can live anywhere — only this
**dedicated runtime copy for Claude Desktop** needs to be outside
`~/Documents`. Whenever you change the code and want Claude Desktop to
pick up the latest version, just re-run the same `uv pip install` command
above (without `-e`) to reinstall over it.

### Configuration

Add a block to `claude_desktop_config.json` (macOS path:
`~/Library/Application Support/Claude/claude_desktop_config.json`). The
key under `mcpServers` (`"Spomory"` in the example below) is what shows
up in the Claude Desktop UI — feel free to rename it to your liking, but
**if you do, also update the log filename referenced in
"Troubleshooting" below**, since the two are tied together. Set `command`
to the absolute path of `memory-core-mcp` inside that **non-Documents**
virtual environment — note that the executable's name doesn't need to
match the display name; it's a fixed entry point generated when the
package is installed. Claude Desktop's subprocess doesn't necessarily
inherit your terminal's `PATH`, so an absolute path is the safest bet:

```json
{
  "mcpServers": {
    "Spomory": {
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

If this JSON file already has other keys (e.g. Claude Desktop's own other
preferences), only add the top-level `mcpServers` key — don't touch
anything else, and back up the file before editing. Fully quit and reopen
Claude Desktop for the config change to take effect.

### Cursor

Cursor uses an MCP config file with the same shape: globally at
`~/.cursor/mcp.json`, or per-project at `.cursor/mcp.json` in the project
root. The content is identical to the Claude Desktop JSON above (the same
`mcpServers.Spomory` key determines what Cursor displays); restart Cursor
after editing. **This has not been tested against a real Cursor
installation** (the dev/verification machine doesn't have Cursor
installed) — it's inferred by analogy with Cursor's official MCP config
docs. After connecting it, re-run the "Verification steps" below to
confirm it actually works.

### Where data lives

Local SQLite data files (graph data + usage stats) live in
`~/.memory-core/` by default (override with `MEMORY_CORE_DATA_DIR`) —
deliberately chosen to be a plain directory outside
Documents/Desktop/Downloads, again to avoid the TCC restriction above,
rather than relying on the process's working directory at startup (a
GUI app spawning a subprocess often gives it an unpredictable cwd).

**Verification steps** (walk through these; should take under 10 minutes):

1. Open Claude Desktop, start a new conversation, and confirm the
   Connectors/MCP tools list near the input box shows `Spomory` connected
   (if it's not connected, the usual cause is a wrong `command` path, or
   a missing `LLM_API_KEY` in the env vars).
2. Have Claude call `add_memory` to write something, e.g. "Please call
   Spomory's add_memory tool to remember: I work as a backend engineer at
   Some Company."
3. Start a new conversation (or continue the same one) and have Claude
   call `search_memory` to ask "Where do I work?", confirming it retrieves
   what was written in step 2.
4. To verify the cloud backend (Epic 8.2), add `DATABASE_URL` to `env`,
   restart Claude Desktop, and repeat steps 2-3 to confirm identical
   behavior.

**Troubleshooting**: if Claude Desktop shows "Server disconnected," the
actual error (not that generic message) is in
`~/Library/Logs/Claude/mcp-server-Spomory.log` (the filename follows
whatever key you used under `mcpServers`, so it changes if you rename the
display name) — check this file first; that's exactly how the TCC
permission issue above was diagnosed.

## Verification status

- **Code + unit tests**: done. `tests/test_mcp_server.py` uses the
  official `mcp` SDK (v2, `MCPServer`)'s `list_tools()` to verify all four
  tools register correctly; `server.py`'s retrieval/write logic reuses
  the Epic 1/2 pipeline already verified against a real LLM + embedding
  model (see `tests/test_e2e_real_llm.py`), and switching the storage
  backend between local SQLite and cloud Postgres has also been verified
  for functional parity (`tests/test_postgres_mcp_parity.py`).
- **Epic 6.2's requirement to "connect to Claude Desktop/Cursor for real
  end-to-end verification"**: done against a real Claude Desktop,
  including a regression check after renaming the server to Spomory —
  `mcp-server-Spomory.log` shows a real `tools/call`, the DB
  (`~/.memory-core/memory_core.sqlite3`) shows a real relation written by
  `add_memory`, and the following `search_memory` call correctly
  triggered embedding-based retrieval. Cursor hasn't been tested on this
  machine (not installed); see the "Cursor" section above for setup
  steps.
