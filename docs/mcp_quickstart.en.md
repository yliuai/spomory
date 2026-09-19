# MCP Server Quickstart

**English | [中文](mcp_quickstart.md)**

Covers TASKS.md Epic 6.2-6.4 (internal task tracker, not part of this
repo). This MCP server shows up in Claude Desktop / Cursor / Codex CLI as
**Spomory** (`src/memory_core/mcp_server/server.py`'s `MCPServer("Spomory")`), and
exposes six tools: `add_memory`, `search_memory`, `get_graph`,
`export_memory`, `forget_memory` (finds the single best-matching memory
for a query and physically deletes it — the first user-facing trigger
for the "true delete" capability behind `export_memory`), and
`forget_all_memory` (physically clears the whole graph in one call — the
bulk counterpart to `forget_memory`). It defaults to a local
`LocalGraphStore` (SQLite file `memory_core.sqlite3`).

> The importable module is still `memory_core`, and the source-install
> package name is still `memory-core` — the PyPI package is published as
> `spomory` instead, with two identical CLI commands, `memory-core-mcp`
> and `spomory-mcp` (same entry point, either name works). Only the
> **name registered with the client** needs to be exactly `Spomory` for
> Claude Desktop/Cursor/Codex CLI to display it that way; the two are
> independent: the `command` field points at whichever executable
> actually runs the code, while the key in the `mcpServers` JSON object is
> what shows up in the Claude Desktop/Cursor UI and names the log file
> (`mcp-server-<key>.log`). If you rename it, change both places, or the
> log filename and the displayed name will stop matching, which makes
> debugging confusing.

## Tools

| Tool | Parameters | What it does |
|---|---|---|
| `add_memory` | `text`, `source_id="mcp-session"` | Extracts facts (entities + relations) from a piece of text and writes them into the memory graph; returns counts of new/merged entities and new relations |
| `search_memory` | `query`, `top_k=10` | Matches the query against stored triples, expands/ranks via Personalized PageRank over the graph, and assembles the result into a natural-language context |
| `forget_memory` | `query` | Finds the **single** relation that best matches the query and physically deletes it; if either endpoint entity is left with no relations, it's cleaned up too, and the deletion is written to the audit log. Deleting only one match at a time is a deliberate, conservative choice — a query vague enough to match several facts should be narrowed and retried rather than risk deleting the wrong ones silently |
| `forget_all_memory` | (no parameters) | Physically deletes the entire memory graph in one call — every entity, relation, and archived history version — and writes one audit log entry. `forget_memory` is deliberately one-fact-at-a-time; this is its bulk counterpart, for a clean-slate reset instead of calling `forget_memory` N times |
| `get_graph` | `entity_name`, `hops=1` | Returns the subgraph around an entity within the given number of hops, as JSON (`entities` + `relations`) |
| `export_memory` | `subject_id="default"` | Exports the entire memory graph as a JSON "memory passport" — the data-ownership guarantee this server is built around |

## Install

```bash
# simplest — the published package, nothing to clone
pip install "spomory[llm,embedding,mcp]"

# from source, for local development:
uv pip install -e ".[llm,embedding,mcp]"
```

A [`Dockerfile`](../Dockerfile) is also in the repo root, for MCP
directories/hosts (e.g. Glama) that deploy from a container image
instead of a package manager. It's a stdio server, so run it with
`docker run -i`; state persists under `/data` if you mount a volume
there.

## Configure

Set the following environment variables (defaults to OpenAI; for a
Chinese-market OpenAI-compatible API, just swap `LLM_BASE_URL`/`LLM_MODEL`):

```bash
export LLM_API_KEY=...
export LLM_BASE_URL=https://api.deepseek.com   # optional, defaults to OpenAI
export LLM_MODEL=deepseek-v4-flash             # optional, defaults to gpt-4o-mini
export EMBEDDING_MODEL=BAAI/bge-m3             # optional, defaults to bge-m3
```

### Running fully local (no cloud LLM calls at all)

By default, embedding already runs locally (the `sentence-transformers`
model above), and only the LLM extraction/generation call goes to
whatever cloud API `LLM_BASE_URL` points at. To make that call local too,
point it at any locally-running OpenAI-compatible server instead — vLLM,
Ollama, and llama.cpp's `llama-server` all expose one, and so does the
MLX ecosystem (`mlx_lm.server`, or the community `vllm-mlx` /
`mlx-openai-server` wrappers):

```bash
# Ollama
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_API_KEY=not-needed   # most local servers don't check this, but the openai SDK requires a non-empty string
export LLM_MODEL=llama3.1       # whatever you've `ollama pull`ed

# vLLM / llama.cpp / MLX: same idea, just the port/model name differ
export LLM_BASE_URL=http://localhost:8080/v1
```

No code change needed — `OpenAICompatibleProvider` already talks to "any
OpenAI-compatible endpoint," this is purely an env var pointing it
somewhere else. The one thing to watch: extraction requires the model to
reliably return valid JSON (`response_format={"type": "json_object"}`);
smaller local models may be less consistent about this and about
extraction quality generally than GPT-4o-mini/DeepSeek.

To also drop the `sentence-transformers`/`torch` dependency (relevant if
you're already running one of the engines above for the LLM anyway, and
don't want a second, heavier ML framework installed just for embedding),
switch the embedding provider too:

```bash
export EMBEDDING_PROVIDER=openai_compatible
export EMBEDDING_BASE_URL=http://localhost:11434/v1   # defaults to LLM_BASE_URL if unset
export EMBEDDING_MODEL=nomic-embed-text                # whatever embedding model that server has loaded
```

`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` fall back to `LLM_BASE_URL`/
`LLM_API_KEY` when unset — convenient for Ollama, which commonly serves
both a chat model and an embedding model from the same port, less so for
vLLM/llama.cpp, which usually run one model per process (so a real setup
with either of those for embedding will typically point
`EMBEDDING_BASE_URL` at a second port running a dedicated embedding
model). When this is set, `pip install spomory[llm,mcp]` is enough — the
`embedding` extra (and the `sentence-transformers`/`torch` install it
pulls in) is entirely unnecessary.

**Verification status**: architecturally this covers all four engines
identically (they all speak the same `/v1/embeddings`/
`/v1/chat/completions` protocol), but only Ollama has actually been
tested end-to-end against a real server in this repo
(`tests/test_openai_compatible_embedding.py`'s real-call test, run
against `ollama serve` + `ollama pull nomic-embed-text`). vLLM,
llama.cpp, and MLX should work the same way but haven't been verified
here yet.

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

## Connecting Claude Desktop / Cursor / Codex CLI

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
after editing. **Verified against a real Cursor installation**
(2026-09-14): `add_memory`/`search_memory`/`forget_memory` and the rest of
the tools call correctly from Cursor's agent.

**GUI entry point**: instead of hunting the filesystem for `mcp.json`,
Cursor's **Customize → MCPs → "+ New MCP Server"** opens
`~/.cursor/mcp.json` directly in a split editor pane — save it and it
behaves exactly like editing the file by hand.

**JSON shape for the remote/cloud version** (the local version uses
`command`+`env`, as in the Claude Desktop example above; the remote
version uses `url`+`headers` instead):

```json
{
  "mcpServers": {
    "spomory-cloud": {
      "url": "https://memory.example.com/mcp-apikey/",
      "headers": {
        "x-api-key": "<the key from /users/register above>"
      }
    }
  }
}
```

(If you're connecting to Spomory's own officially hosted service rather
than a self-deployed instance, the real `url` is
`https://api.yliuai.com/mcp-apikey/` — that domain is already public,
referenced in `docs/privacy_policy_draft.en.md`, not internal
information.) **This remote connection path has also been verified
against a real Cursor installation** (2026-09-15).

### Codex CLI

Codex CLI's MCP config is TOML, not the JSON shape Claude Desktop/Cursor
use — default path `~/.codex/config.toml`, with per-project config also
supported at `.codex/config.toml` (trusted projects only):

```toml
[mcp_servers.Spomory]
command = "/absolute/path/to/memory-core-venv/bin/memory-core-mcp"

[mcp_servers.Spomory.env]
LLM_API_KEY = "your LLM API key"
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-flash"
```

Or add it with the official CLI command instead of editing the file by hand:

```bash
codex mcp add Spomory \
  --env LLM_API_KEY=your-key --env LLM_BASE_URL=https://api.deepseek.com --env LLM_MODEL=deepseek-v4-flash \
  -- /absolute/path/to/memory-core-venv/bin/memory-core-mcp
```

`codex mcp list` confirms it registered. **Verified against a real Codex
CLI installation** (2026-09-14): tool-call behavior matches Claude
Desktop/Cursor.

**GUI configuration**: the Codex client (desktop/IDE builds) also has a
point-and-click way to add a server without hand-editing `config.toml`:
**Plugins → Manage (top right) → MCPs → "+ Add server"**, which opens a
"Connect to a custom MCP" form with two connection types, matching
Spomory's local and remote deployments respectively:

- **STDIO** (local Spomory):
  - Name: `Spomory`
  - Command to launch: `/absolute/path/to/memory-core-venv/bin/memory-core-mcp`
    (same value as `command` in the TOML example above)
  - Arguments: leave blank
  - Environment variables: add three rows — `LLM_API_KEY`, `LLM_BASE_URL`,
    `LLM_MODEL` — same values as the TOML example
  - Working directory: can be left blank

- **Streamable HTTP** (remote/cloud Spomory, see "Connecting to a remote
  Spomory" below):
  - Name: `Spomory Cloud`
  - URL: `https://memory.example.com/mcp-apikey` (swap in your real
    deployment's domain — this is the API-key mount, not the OAuth one:
    this form has no full OAuth-authorization-flow entry point, only a
    "Bearer token" field and plain headers)
  - Bearer token env var: leave blank — Spomory's remote API-key mount
    expects an `x-api-key` header, not `Authorization: Bearer`
  - Headers from environment variables: add one row, Key = `x-api-key`,
    Value = the name of a local environment variable (e.g.
    `SPOMORY_API_KEY`) that you've already set to the key returned by
    `/users/register` in "Connecting to a remote Spomory" below — reference
    it indirectly via an env var; don't paste the raw key into the plain
    "Headers" field (that one stores the literal value straight into
    Codex's config file).

**Both connection types (STDIO and Streamable HTTP) on this path have been
verified against a real Codex client** (2026-09-15): the GUI-entered
configuration connects to Spomory correctly (tested against both the
local and remote deployments), with tool-call behavior matching the
CLI/`config.toml` approach above.

### Where data lives

Local SQLite data files (graph data + usage stats) live in
`~/.memory-core/` by default (override with `MEMORY_CORE_DATA_DIR`) —
deliberately chosen to be a plain directory outside
Documents/Desktop/Downloads, again to avoid the TCC restriction above,
rather than relying on the process's working directory at startup (a
GUI app spawning a subprocess often gives it an unpredictable cwd).

**Encrypted at rest by default (Epic 11.2)**: every entity/relation stored
in `memory_core.sqlite3` is ciphertext, not plaintext — the first startup
generates an `encryption.key` (mode 600) alongside it automatically, and
every later startup reuses that same key. The key lives right next to the
database rather than in a secrets manager — for a single-user local tool,
the threat model is "someone gets the db file/a backup of it," not "this
whole machine is compromised" (in which case where the key lives wouldn't
matter anyway). **Upgrading from a version before encryption existed**:
the first startup on the new version detects the old plaintext database
and migrates it in place automatically — the original file is backed up
to `memory_core.sqlite3.pre-encryption-backup` first (not deleted
automatically; safe to remove once you've confirmed the new database
looks right). No data loss, no manual steps required.

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
4. Have Claude call `forget_memory`, e.g. "Please call Spomory's
   forget_memory tool to forget that I work as a backend engineer at Some
   Company," then repeat step 3's query and confirm that memory is gone.
5. To verify the cloud backend (Epic 8.2), add `DATABASE_URL` to `env`,
   restart Claude Desktop, and repeat steps 2-4 to confirm identical
   behavior.

**Troubleshooting**: if Claude Desktop shows "Server disconnected," the
actual error (not that generic message) is in
`~/Library/Logs/Claude/mcp-server-Spomory.log` (the filename follows
whatever key you used under `mcpServers`, so it changes if you rename the
display name) — check this file first; that's exactly how the TCC
permission issue above was diagnosed.

## Remote access (API key, Epic 11.5, optional)

Everything above is the local stdio server — no registration needed, data
stays on your machine, still the default recommended way to connect. If you
don't want to run a Python environment locally at all (e.g. connecting from
Claude's web app, or getting listed on a marketplace like China's ModelScope
MCP directory that only accepts a reachable HTTPS endpoint),
`src/memory_core/mcp_server/remote.py` + `src/cloud_api/` provide a second,
API-key-authenticated remote path. Same six tools, same behavior; the
differences are:

- Each user's memories live in a shared Postgres database, isolated per
  `user_id` (`PostgresGraphStore(dsn, user_id)`), not a local SQLite file.
- Authentication is an API key (`x-api-key` header), not full OAuth — enough
  for a platform like ModelScope/Doubao/Coze that just requires a reachable
  HTTPS endpoint, but not enough to meet Anthropic's official Connector
  Directory requirements (OAuth 2.1 + PKCE).

### Deploy

```bash
uv pip install "memory-core[llm,embedding,mcp,cloud] @ git+https://github.com/yliuai/spomory.git"

export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # required, no local-SQLite fallback
export LLM_API_KEY=...
export MCP_ALLOWED_HOSTS=memory.example.com,memory.example.com:443  # required, see the security note below
export CORS_ALLOWED_ORIGINS=https://spomory.yliuai.com  # optional, this is already the default
export PORT=8000  # optional, defaults to 8000

memory-core-mcp-remote
```

**`MCP_ALLOWED_HOSTS` must be set to the real public hostname(s) this
deploys behind** (comma-separated, `host:*` wildcards a port): this is the
MCP SDK's built-in DNS-rebinding protection, which checks the request's
`Host` header and returns 421 for anything not on the allowlist. Leaving it
unset doesn't mean "allow everything" — it means every request is rejected
by default (fail closed rather than leave an implicit allow-all-hosts back
door); this was verified with a local smoke test using a fake `Host` header
(see "Verification status" below).

**`CORS_ALLOWED_ORIGINS` is a separate layer** from `MCP_ALLOWED_HOSTS`/
`MCP_ALLOWED_ORIGINS` above, which govern the MCP transport's own Origin
check and never add CORS response headers — a browser `fetch()` (e.g. the
marketing site's signup form) is still blocked by the browser itself
regardless of what this service returns. `create_app` takes a new
`cors_allowed_origins` parameter that adds `Access-Control-Allow-Origin`
for plain HTTP routes like `/users/register`; leaving it unset keeps CORS
fully off (unchanged from before this parameter existed), it never
defaults open to `*`. Comma-separated for multiple origins.

### Use it

```bash
curl -X POST https://memory.example.com/users/register \
  -H "Content-Type: application/json" -d '{"email": "you@example.com"}'
# the api_key in the response (starts with mck_) is only ever shown once -- save it
```

Configure a remote MCP connection in Claude Desktop/Cursor (exact JSON shape
per that client's current docs): `url` is `https://memory.example.com/mcp-apikey`,
with an `x-api-key: <the key from above>` header.

**Calling this endpoint again with the same email is safe** — it resolves
to the same account (`user_id` stays the same) and issues a fresh key each
time, so losing a key just means registering again rather than needing a
separate recovery flow; old keys keep working until explicitly revoked.
There's basic rate limiting to stop scripted abuse (5/hour per email,
20/hour per IP, 429 past that).

**This endpoint itself doesn't verify email ownership** — the key goes
straight back in the response to whoever calls it, so typing in someone
else's email gets a working key for their account; rate limiting doesn't
stop someone deliberately targeting one specific email. Fine for curling
with your own email, but **don't wire this one directly into a public web
form**.

### Email-verified registration (for a public web form)

```bash
curl -X POST https://memory.example.com/users/register/request \
  -H "Content-Type: application/json" -d '{"email": "you@your-real-domain.com"}'
# the response is just "check your email" -- no key in this response

# clicking the link in that email (GET /users/register/verify?token=...)
# is what actually displays the key, on the page it opens
```

**Use a real, deliverable address here, not a copy-pasted `you@example.com`**
— the mail provider (Resend, in this deployment) rejects sending to RFC
2606 reserved documentation domains like `example.com`/`example.org` and
returns a 503. This isn't hypothetical: it's a real bug that got hit
during deployment verification (unhandled at the time, so it surfaced as
a bare 500 rather than the current clean 503) -- 503, not 502, because
this deployment sits behind Cloudflare, and production testing confirmed
Cloudflare silently replaces a 502/504 response body with its own generic
error page regardless of what the origin actually sent, which would have
swallowed this message entirely. It's fixed to catch and report the
failure cleanly now, but hitting the underlying trigger (a placeholder
domain) is still avoidable, so the example here uses a different
placeholder instead of relying on the error message alone.

The difference from the plain version above: the key is only ever issued
and shown after that email link is clicked, so no inbox access means no
key — this is what actually closes the "typed in someone else's email"
gap, not just rate limiting around it. `register_or_reissue_key` underneath
behaves the same as the direct path (same email → same account, a fresh
key each call), just gated on that extra verification step. Needs
`RESEND_API_KEY`/`EMAIL_FROM` set to deploy (independent of OAuth — you
don't need the OAuth flow turned on to use this pair); `PUBLIC_BASE_URL`
is optional and defaults to `OAUTH_ISSUER_URL` when that's already set to
the same host.

### Not part of this path

- Origin header validation (another Anthropic Connector Directory
  requirement, handled separately from OAuth — see the next section for
  what's in scope there).
- Actually exposing this to the public internet — domain, TLS, firewall —
  those are deployment decisions you make; this only provides the code and
  local verification.
- Two-way sync between local and cloud memories — the local stdio server and
  this remote server are currently two independent distribution channels
  that don't share data.

## OAuth 2.1 (for Anthropic's official Connector Directory)

The API-key path above is enough for ModelScope-style platforms, but
Anthropic's official Connector Directory requires OAuth 2.1 + PKCE and
rejects plain API keys. This is a third, separate access path — a
different mount (`/mcp-apikey` stays API-key, `/mcp` is OAuth-only) behind
the same underlying memory graph (both resolve to the same `user_id`
against the same Postgres store, not two separate datasets).

**Why the API-key mount is the one named `/mcp-apikey`, not the OAuth
one**: the OAuth mount is the one that actually gets submitted to
Anthropic's directory and shows up in marketplace search/one-click-connect
UI, and real Directory listings' Connector URLs conventionally end in
`mcp` — so that name went to the one facing the marketplace. The API-key
mount's URL only ever gets pasted by hand into a client's own config file;
nobody discovers it through a listing, so it has no such naming pressure.

**Why they can't share one mount**: once an `MCPServer` is configured
with `auth_server_provider`, the `mcp` SDK wraps *every* request to that
mount in `RequireAuthMiddleware` — anything without a valid
`Authorization: Bearer` gets a 401 before it ever reaches tool code.
Turning OAuth on for the same mount as the API-key path would break every
existing `x-api-key`-only client (Cursor, ModelScope, `mcp-remote`), so
OAuth gets its own mount instead.

### `/mcp` is only the Connector URL (where tools get called) — not where authorization happens

**`/mcp` is the URL an MCP client connects to and actually calls
`add_memory`/`search_memory` on** (the OAuth "resource server"). The
authorization flow itself — `/authorize`, `/token`, `/register`,
`/.well-known/oauth-authorization-server` — lives **at the domain root**,
not under `/mcp` (e.g. `https://api.example.com/authorize`, not
`https://api.example.com/mcp/authorize`).

This isn't arbitrary: the `mcp` SDK builds those URLs by concatenating a
fixed path onto `issuer_url` as a plain string
(`mcp/server/auth/routes.py`: `str(issuer_url).rstrip("/") + "/authorize"`
and similar) — it has no idea where the ASGI app implementing those routes
actually gets mounted. This project's `issuer_url` has no path component
(just the bare domain), so those endpoints have to be reachable at the
root. **This was a real bug caught during development** (back when the
OAuth mount's path was still called `/mcp-oauth`, before it got renamed to
`/mcp` to match the "Connector URLs end in mcp" convention — the bug and
the rename are two separate things): the first version mounted the entire
OAuth-configured `MCPServer` under that prefix, which nested
`/authorize`/`/token`/`.well-known` under it too — the metadata document
advertised `https://host/authorize`, but that path only actually existed
at `https://host/<prefix>/authorize`, so a real client following the
metadata would 404. The fix mounts that ASGI app at the FastAPI root
instead, using its own internal `streamable_http_path="/mcp"` to place the
tool-calling endpoint at `/mcp` while `/authorize` etc. land correctly at
the root. Regression coverage: `tests/test_oauth_mount_routing.py`
(including a case verifying `/mcp-apikey` and `/mcp` coexist without
either shadowing the other).

**Login is an email magic link**: there's no password system in this
project, so `/authorize` collects an email, sends a one-time link, and only
generates the real OAuth authorization code once that link is clicked and
redirects back to the connecting client. Sending goes through
[Resend](https://resend.com) rather than raw SMTP from the VPS — a fresh
cloud server's outbound IP has no sending reputation and gets blocklisted
easily.

**New environment variables** (on top of the existing `memory-core-mcp-remote`
ones; leaving `OAUTH_ISSUER_URL` unset keeps the OAuth mount disabled
entirely, so an existing API-key-only deployment is unaffected):

```bash
export OAUTH_ISSUER_URL=https://api.example.com          # required, the OAuth on-switch
export OAUTH_RESOURCE_SERVER_URL=https://api.example.com/mcp  # optional, derived from issuer by default
export RESEND_API_KEY=re_...    # from a Resend account you register — domain verification happens there too
export EMAIL_FROM="Spomory <noreply@example.com>"
```

### Origin header validation + RFC 8707 resource (audience) validation

Both of these got added later (`create_app`/`SpomoryOAuthProvider` gained
`allowed_origins`/`resource_url` parameters):

- **Origin validation**: reading Anthropic's own "Testing your connector"
  docs turned up that this isn't actually a "must implement" item on the
  review checklist — it instead shows up in their troubleshooting section
  as a documented cause of `initialize` failures ("overly strict
  Origin-header validation rejecting Anthropic's own requests"). Leaving
  the allowlist empty means *any* request carrying an Origin header gets
  rejected, which was exactly that overly-strict case. Fixed by adding a
  `MCP_ALLOWED_ORIGINS` env var (defaults to `https://claude.ai`), allowing
  only that one known-legitimate origin without weakening the check
  against anything else; requests with no Origin header at all (most
  non-browser MCP clients) are unaffected either way.
- **RFC 8707 resource/audience validation**: `SpomoryOAuthProvider` gained
  a `resource_url` parameter, and `load_access_token` now checks a token's
  `resource` claim (when the client sent one) against this server's own
  resource URL, using canonical-form comparison (`rstrip("/").lower()`)
  rather than byte-for-byte — this stops a token minted for a different
  service from being replayed here. A missing `resource` claim isn't
  treated as a mismatch (the parameter is optional per the RFC), and a
  refreshed token keeps the original resource claim. This work also
  confirmed the RFC 9728 protected-resource metadata endpoint
  (`/.well-known/oauth-protected-resource/mcp`) was already working
  correctly.

Regression coverage: `tests/test_oauth_store.py` (four resource/audience
scenarios) and `tests/test_oauth_mount_routing.py`
(`test_origin_allowlist_admits_the_configured_origin_and_rejects_others`).
Writing that Origin test surfaced two test-design traps: the auxiliary
routes (`.well-known/*`) aren't covered by `TransportSecuritySettings` at
all — only the actual MCP resource endpoint (`/mcp`) is — and a request
without a real valid Bearer token gets 401'd by `RequireAuthMiddleware`
before Origin validation is ever reached, so testing Origin rejection
requires minting a genuinely valid token via the real provider flow first.

**Not part of this path yet**: actually
submitting to Anthropic's developer portal for Connector review (an
operational step, for once this has run through a real Claude Desktop
browser authorization flow on the live deployment); password
reset/full account management — a magic link is enough for login alone.

## Verification status

- **Code + unit tests**: done. `tests/test_mcp_server.py` uses the
  official `mcp` SDK (v2, `MCPServer`)'s `list_tools()` to verify all six
  tools register correctly, plus dedicated tests for `forget_memory`
  (matched-relation deletion, orphaned-entity cleanup, audit log entry)
  and `forget_all_memory` (full-graph wipe including archived history);
  `server.py`'s retrieval/write logic reuses
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
  triggered embedding-based retrieval. **Cursor and Codex CLI have also
  been verified against real installations (2026-09-14)**, with tool-call
  behavior matching Claude Desktop; see the "Cursor" and "Codex CLI"
  sections above for setup steps.
- **`forget_memory` verified live**: saying "remember: I have a cat named
  Bo" in Claude Desktop extracted two relations (`I-have-cat`,
  `cat-named-Bo`); saying "forget that I have a cat" afterward had
  `forget_memory` delete only the single best semantic match
  (`cat-named-Bo`, plus the now-orphaned `Bo` entity), leaving
  `I-have-cat` untouched. That's the intended conservative behavior
  (delete the one best-matching relation per call, not a fuzzy sweep) —
  not a bug — but it means a sentence that gets extracted into multiple
  relations may need more than one (more specific) `forget_memory` call to
  fully erase. Confirmed against both the database and the
  `memory_core_audit.sqlite3` audit entry
  (`{"entities_deleted": 1, "relations_deleted": 1}`).
- **`forget_all_memory` (added 2026-09-14)**: a direct response to that
  limitation showing up in real use — an account with 4 stored facts
  wanting a reset meant calling `forget_memory` 4 times, each one gated
  behind a manual "Allow once" approval in Claude Desktop.
  `forget_all_memory` exists to fix exactly that observed friction: one
  call physically deletes the whole graph (including archived history),
  no need to narrow and retry per fact.

- **Remote access (Epic 11.5) — honest verification status**: the
  `user_id`-isolation added to `PostgresGraphStore` and mounting the MCP
  streamable-http endpoint in `cloud_api/app.py` have been verified for the
  parts that don't require Postgres:
  - A fake-request smoke test (`TestClient`, a local `LocalGraphStore`
    rather than the real `PostgresGraphStore`) ran the full
    `/users/register` → `/mcp` `initialize` handshake, surfacing and fixing
    two real bugs along the way: (1) FastAPI/Starlette don't propagate
    lifespan events into an `app.mount()`-ed sub-application by default, so
    the MCP session manager never started and every tool call failed with
    `RuntimeError: Task group is not initialized` — fixed by manually
    entering the sub-app's `lifespan_context` inside `create_app`'s own
    lifespan; (2) the MCP SDK's built-in DNS-rebinding protection rejects
    every `Host` header by default, requiring the new `allowed_hosts`/
    `MCP_ALLOWED_HOSTS` setting to connect at all. Both were found by
    reproducing the failure and reading the SDK source, not guessed.
  - The new cross-tenant isolation test in `tests/test_postgres_store.py`
    and `tests/test_remote_mcp_server.py` (rejecting missing/invalid API
    keys, two users not seeing each other's memories, usage/audit recorded
    under the real resolved `user_id`) were written and pass.
  - **2026-09 update: actually deployed to the public internet and
    verified there.** A Tencent Cloud server (Ubuntu 24.04) running
    postgresql 16 + nginx + systemd, domain proxied through Cloudflare. The
    Postgres-dependent tests above now pass against that server's real
    database, and `POST /users/register` / `POST /mcp/` (a real
    `initialize` handshake) were both confirmed working over the real
    public domain, not a loopback test. A real deployment bug surfaced and
    got fixed along the way: Cloudflare's "Automatic SSL/TLS" mode probes
    whether the origin supports 443, and the origin only had port 80 open
    — the probe connection hung until timeout instead of falling back
    cleanly; switching to Flexible mode fixed it. Not done yet: connecting
    a real Claude Desktop/Cursor client (only curl-simulated MCP calls so
    far), submitting to the ModelScope MCP marketplace.

- **OAuth 2.1 — honest verification status**: every method of
  `SpomoryOAuthProvider`'s Protocol (client registration, `authorize` ->
  pending-request storage, authorization-code issuance and one-time
  consumption, access/refresh token issuance/verification/rotation/revocation)
  is tested directly in `tests/test_oauth_store.py`; the full
  `/oauth/login` -> `/oauth/verify` magic-link HTTP flow passes in
  `tests/test_oauth_login_flow.py` using a fake `EmailSender` (no real send
  tested yet — no Resend account configured); resolving an OAuth token to a
  `user_id` (the `get_access_token()` contextvar mechanism) is unit-tested
  in `tests/test_remote_oauth_context.py`, and the full "real Postgres +
  OAuth Bearer token calling add_memory/search_memory" path has been run
  against the same live server's database in `tests/test_remote_mcp_server.py`.
  A real routing bug got caught and fixed along the way, too — `/mcp-oauth`
  originally mounted the entire OAuth-configured `MCPServer` under that
  prefix, nesting `/authorize`/`/token`/`.well-known` under it as well, but
  the SDK builds its metadata document's URLs from the path-less
  `issuer_url` (e.g. `https://host/authorize`), which only actually existed
  at `https://host/mcp-oauth/authorize` — a real client following the
  metadata would 404. Local tests never caught this (they called Python
  methods directly, never the real HTTP routes); it only surfaced when
  asked point-blank whether `/mcp-oauth` was the actual Connector URL,
  which prompted checking the real routing. Fixed, with dedicated
  regression coverage in `tests/test_oauth_mount_routing.py` (four cases,
  all hitting real HTTP paths rather than internal objects), re-verified
  against the live server's real Postgres. Afterwards, the OAuth mount got
  renamed from `/mcp-oauth` to `/mcp` (API-key moved to `/mcp-apikey`) to
  match the real-world convention that Connector URLs end in `mcp` — added
  a case verifying both mounts coexist without shadowing each other, also
  re-verified against real Postgres.

  **2026-09 update: actually deployed and walked through by hand end to
  end.** A real Resend account got registered and `OAUTH_ISSUER_URL`/
  `RESEND_API_KEY` configured in production, surfacing two more real bugs:
  the login email's link was a relative path (email clients have no
  "current page" to resolve it against, so it opened with "oauth" read as a
  bare hostname), and `/oauth/verify`'s final redirect was built by naive
  string concatenation, producing a malformed URL whenever the OAuth
  client's own callback URL already carried its own query string (true of
  MCP Inspector's). Both fixed — see `运维.md`'s full writeup. A fourth
  issue surfaced after those fixes and turned out not to be our code at
  all: MCP Inspector tracks the in-progress OAuth flow in
  `sessionStorage`, which isn't shared across browser tabs, and clicking
  the emailed link normally opens a new one — losing that tracking data.
  That's an Inspector architecture limitation (a real Claude Desktop uses
  an OS-level deep link back into the same running app, so this wouldn't
  come up there); the workaround was pasting the link into the original
  tab instead of opening it fresh. With that, a real connection went all
  the way through: `add_memory`/`search_memory` both succeeded, the
  written data was confirmed in production Postgres under the correct
  `user_id`, and the test memory was cleaned up afterward.

  **2026-09-06 update: Origin header validation and RFC 8707 audience
  validation are done and deployed too.** See the "Origin header
  validation + RFC 8707 resource (audience) validation" section above.
  The production deployment also needed a real SQLite schema migration
  (`oauth_access_tokens`/`oauth_refresh_tokens` gained a `resource`
  column; the original file was backed up first), after which
  `test_oauth_store.py`/`test_oauth_login_flow.py`/
  `test_oauth_mount_routing.py`/`test_remote_oauth_context.py`/
  `test_remote_mcp_server.py` were all re-run against the real production
  Postgres (27 passed), alongside a full local test run (116 passed, 17
  skipped) and a clean `ruff check`. **Not done yet**: actually
  submitting to Anthropic's developer portal for review.
