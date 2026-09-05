# Spomory

**English | [中文](README.zh-CN.md)**

The core engine behind a personal AI memory product: HippoRAG-style
retrieval (query→triple matching + personalized PageRank diffusion) +
a LightRAG-style dual-layer incremental knowledge graph + a lightweight
GRPO-trained memory-management policy, exposed to Claude Desktop / Cursor
and other clients via an MCP server, with a path to a cloud deployment
(Postgres backend, FastAPI auth/billing skeleton) already scaffolded.

> Spomory is the product/client-facing display name. The Python package
> name, CLI command (`memory-core-mcp`), and module name (`memory_core`)
> are unchanged — see the "Quickstart: MCP Server" section below.

## What's implemented

- **Pluggable LLM / embedding providers**: defaults to any OpenAI-compatible
  API (including Chinese-market LLM providers) + local
  `sentence-transformers` (default `bge-m3`, bilingual Chinese/English).
- **Dual-layer incremental knowledge graph**: entities and relations are
  modeled as independent layers; new data is only extracted and merged in,
  never a full rebuild. Defaults to a local `LocalGraphStore`
  (networkx + SQLite); a `PostgresGraphStore` cloud implementation also
  exists, and both share the same behavioral contract test suite.
- **HippoRAG 2-style retrieval**: the query is matched directly against
  triples rather than only against entity nodes; the matched seed nodes
  are diffused via personalized PageRank for multi-hop association, then
  assembled into a natural-language context (with source timestamps, so
  "when did I mention X" is answerable).
- **Memory management**: an ADD/UPDATE/DELETE/NOOP action space, with a
  rule-based default policy (`RuleBasedPolicy`) and a full GRPO training
  pipeline (`memory_manager/train_grpo.py`, actually run and verified on
  a real GPU).
- **MCP Server**: exposes five tools — `add_memory`, `search_memory`,
  `get_graph`, `export_memory`, `forget_memory` — verified end-to-end
  against a real Claude Desktop.
- **Memory passport export + true delete**: a JSON-LD style export format,
  physical deletion, and an audit log.
- **Multimodal image verification**: image captioning → reuses the text
  extraction pipeline → CLIP cross-checks candidate triples. Honestly
  positioned as "verification," not "native cross-modal extraction."
- **Cloud skeleton**: FastAPI user auth/API keys/quotas, a Stripe webhook
  billing scaffold (skeleton-level only, not production-deployed).

## Project layout

```
src/
├── memory_core/
│   ├── graph/            # entity/relation models, storage adapters (local SQLite / cloud Postgres), incremental writes
│   ├── retrieval/        # query→triple matching, personalized PageRank, context assembly
│   ├── memory_manager/   # action space, reward functions, GRPO training script, policy inference
│   ├── multimodal/       # image captioning + CLIP verification
│   ├── mcp_server/       # MCP Server (the distribution entry point)
│   ├── export/           # memory passport export format + true delete
│   ├── llm/              # pluggable LLM/embedding providers
│   ├── audit.py          # deletion audit log
│   └── usage.py          # retention/usage tracking
└── cloud_api/            # FastAPI cloud service skeleton (auth, quotas, billing)
benchmarks/                # LoCoMo/LongMemEval evaluation harness + multimodal comparison experiments
tests/                     # 94+ tests, from unit tests to real LLM/GPU/Postgres end-to-end verification
docs/                      # per-epic design notes, verification reports, runbooks (see index below)
```

## Installation

Prerequisites: Python **3.11+**, [uv](https://docs.astral.sh/uv/getting-started/installation/)
(no uv? `python -m venv` + `pip install -e` works as a substitute for the
`uv` commands below).

```bash
git clone <this repo's URL> memory-core && cd memory-core
uv venv --python 3.11 .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Pick dependency groups as needed — they can be combined, no need to install everything:
uv pip install -e ".[dev]"                 # required to run tests/lint
uv pip install -e ".[llm,embedding]"       # required for the "minimal working memory system" (see the demo below)
uv pip install -e ".[mcp]"                 # extra: connecting to Claude Desktop/Cursor
uv pip install -e ".[rl]"                  # extra: GRPO training (requires a GPU + CUDA)
uv pip install -e ".[cloud]"               # extra: cloud API / Postgres backend
uv pip install -e ".[multimodal]"          # extra: image + CLIP verification
```

The `embedding` group downloads the default model `BAAI/bge-m3` from
HuggingFace on first use (~2.2GB) — make sure huggingface.co is reachable
(if you're behind the Great Firewall, `export HF_ENDPOINT=https://hf-mirror.com`
routes through a mirror). You can also swap in a smaller model via
`export EMBEDDING_MODEL=<any sentence-transformers model name>`.

The `llm` group itself downloads nothing, but **`LLM_API_KEY` must be set
at runtime** (any OpenAI-compatible Chat Completions endpoint works — OpenAI,
DeepSeek, Qwen, etc.):

```bash
export LLM_API_KEY=sk-...
export LLM_BASE_URL=https://api.deepseek.com   # optional; defaults to OpenAI's endpoint
export LLM_MODEL=deepseek-chat                 # optional; defaults to gpt-4o-mini
```

### Run a minimal example (no MCP, plain Python calls)

With `dev` + `llm` + `embedding` installed and the three env vars above
set, this script exercises the full "write a memory → retrieve it"
pipeline directly (the same logic behind `mcp_server/server.py`'s
`add_memory`/`search_memory` tools, just calling the library directly
instead of going through the MCP protocol layer):

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

store = LocalGraphStore("demo.sqlite3")          # a local file; delete it to reset
llm = OpenAICompatibleProvider()                 # reads LLM_API_KEY etc. from the environment
embedder = SentenceTransformerProvider()         # downloads bge-m3 on first run

# 1. Write a memory: the LLM extracts triples, incrementally merged into the graph
ingestor = IncrementalIngestor(store, llm, policy=RuleBasedPolicy())
result = ingestor.ingest("I do AI research at CAS, mostly in Python.", source_id="demo")
print(f"added {result.new_entities} entities, {result.new_relations} relations")

# 2. Retrieve: match the query against triples -> PPR diffusion -> assemble a natural-language context
query = "Where do I work?"
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

Here's real output from a live run against DeepSeek with the exact input
shown above (not fabricated, not cleaned up — this is what actually came
back):

```
added 3 entities, 2 relations
I do AI research at CAS (recorded at 2026-09-05 10:40:00).I do AI research mostly in Python (recorded at 2026-09-05 10:40:00).
```

Exact wording and entity/relation counts depend on the LLM's own
extraction and will vary between runs, but as long as the env vars are
set correctly, non-empty output means the pipeline works end to end.
`retrieval/ranker.py` detects whether a relation's text is CJK or not and
renders it accordingly (no spaces + a Chinese timestamp label for CJK,
spaced words + an English timestamp label otherwise), so English input no
longer comes out as one run-on word like earlier versions of this demo
did.

## Quickstart: MCP Server (connecting to Claude Desktop / Cursor)

This MCP server shows up in Claude Desktop / Cursor as **Spomory** (set
by the `mcpServers` key in the client's config file — see the docs
below). The Python package name and CLI command are still
`memory-core` / `memory-core-mcp`; the two are independent of each other.

With the `mcp` dependency group installed and `LLM_API_KEY` etc. set:

```bash
uv pip install -e ".[llm,embedding,mcp]"
memory-core-mcp   # stays running as a stdio MCP server, waiting for a client to connect
```

Data lives in `~/.memory-core/` by default (override with
`MEMORY_CORE_DATA_DIR`); setting `DATABASE_URL` switches to the Postgres
backend instead of local SQLite.

Connecting it to Claude Desktop / Cursor requires registering this
command's **absolute path** in the client's config file (don't rely on
`PATH`). Full steps, a config file example, and a real gotcha we actually
hit (macOS's TCC privacy protection blocks a venv running under
`~/Documents`) are in
[`docs/mcp_quickstart.en.md`](docs/mcp_quickstart.en.md).

## Measured results

Real runs against DeepSeek on 84 QA pairs from LoCoMo-10 (conv-26, first
150 turns) — not cherry-picked, and not competitive with the bigger
players' published numbers yet:

| Metric | Value |
|---|---|
| Recall@10 (did the right evidence turn make it into context) | 52.4% |
| Accuracy — strict substring match | 19.0% |
| Accuracy — LLM-judged (looser, wording-tolerant) | 44.0% |

A prior run (before a fix that folds dates into extracted predicates so
"when" questions are answerable) scored lower on accuracy but higher on
recall (62.0%) — the fix traded some retrieval recall for a real
+14.3-point accuracy gain, and we went and found out exactly why instead
of just reporting the accuracy number: the date-folding instruction
sometimes misfires on content-free small talk ("Thanks!" → "thanked on
2023-07-03"), and those extra low-value triples crowd out relevant ones
out of the fixed top-10 retrieval window. Full numbers, per-category
breakdown, and the side-by-side extraction comparison that found this are
in [`docs/benchmark_smoke_test.md`](docs/benchmark_smoke_test.md).

## Testing

```bash
pytest                    # everything
pytest -m "not slow"      # skip tests that download models / train — runs in seconds
```

Most of the "slow" tests aren't mocked — they're real calls (real LLM API,
real local embedding model, real CLIP model) and need the corresponding
env vars (`LLM_API_KEY`, etc.) or an already-downloaded model cache.

## Documentation index

| Doc | Content |
|---|---|
| [mcp_quickstart.en.md](docs/mcp_quickstart.en.md) ([中文](docs/mcp_quickstart.md)) | MCP Server install, configuration, connecting Claude Desktop/Cursor, real-world gotchas |
| [graph_store_interface.md](docs/graph_store_interface.md) *(Chinese only)* | Storage adapter interface design |
| [export_format.md](docs/export_format.md) *(Chinese only)* | The "memory passport" export format |
| [dataset_format.md](docs/dataset_format.md) *(Chinese only)* | GRPO training data format and how the real dataset was generated |
| [methodology.md](docs/methodology.md) *(Chinese only)* | Technical methodology: what's actually verified vs. still open |
| [benchmark_smoke_test.md](docs/benchmark_smoke_test.md) *(Chinese only)* | Real LoCoMo benchmark results and failure-case analysis |
| [memory_manager_eval.md](docs/memory_manager_eval.md) *(Chinese only)* | Rule-based vs. GRPO-trained policy comparison, including the debugging process |
| [multimodal_verification.md](docs/multimodal_verification.md) *(Chinese only)* | Image + CLIP verification experiment results |
| [gpu_training_runbook.md](docs/gpu_training_runbook.md) *(Chinese only)* | GPU training environment setup log (including real gotchas hit) |
| [postgres_setup.md](docs/postgres_setup.md) *(Chinese only)* | Cloud Postgres backend deployment log |
| [leaderboard_submission.md](docs/leaderboard_submission.md) *(Chinese only)* | Third-party leaderboard research |
| [mvp_scope.md](docs/mvp_scope.md) *(Chinese only)* | MVP scope definition |
| [privacy_policy_draft.md](docs/privacy_policy_draft.md) / [product_copy_memory_passport.md](docs/product_copy_memory_passport.md) *(Chinese only)* | Draft privacy policy / external-facing product copy |

The docs above are currently Chinese-only except where an English version
is linked; they'll be translated as the project's English-speaking
audience grows. If you need one translated sooner, open an issue.

## Known limitations

- Multimodal verification for voice input (ASR + audio embedding) isn't
  implemented yet.
- The GRPO training dataset (140 real samples) and the number of training
  steps are still small; `memory_manager_eval.md` honestly documents how
  that limits training effectiveness.
- The cloud API/billing is skeleton-level only and hasn't been connected
  to a real production environment.

## License

See [LICENSE](LICENSE).
