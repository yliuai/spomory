<!-- mcp-name: io.github.lyf-wxy/spomory -->

# Spomory

**English | [中文](README.zh-CN.md)**

Spomory gives Claude Desktop, Cursor, and Codex CLI a memory that
persists across sessions — and is shared between all three. Tell one of
them something once (a project detail, a preference, a fact about
yourself) and any of them can recall it later, without you repeating
yourself.

It runs as an [MCP](https://modelcontextprotocol.io/) server, either
locally on your own machine (free, nothing leaves your computer) or as a
hosted cloud service (free signup, memory follows you across devices).
The rest of this README covers the local path; for the cloud path see
[spomory.yliuai.com/get-started/remote](https://spomory.yliuai.com/get-started/remote).

Curious what it looks like before installing anything? There's a
no-signup demo at [spomory.yliuai.com](https://spomory.yliuai.com) —
paste in some text, see the entities and relations it extracts.

## Get started

Requires Python 3.11+.

**1. Install**

```bash
pip install "spomory[llm,embedding,mcp]"
```

**2. Give it an LLM.** Spomory uses an LLM to turn what you tell it into
structured facts. Any OpenAI-compatible API works — OpenAI, DeepSeek,
Qwen, etc.:

```bash
export LLM_API_KEY=sk-...
export LLM_BASE_URL=https://api.deepseek.com   # optional, defaults to OpenAI
export LLM_MODEL=deepseek-chat                 # optional, defaults to gpt-4o-mini
```

**3. Connect it to your client.** Claude Desktop, Cursor, and Codex CLI
each need a few lines added to a config file, pointing at the
`spomory-mcp` command. The exact steps, a config file example for each
client, and a real gotcha we hit (macOS blocking a venv that lives under
`~/Documents`) are in
[`docs/mcp_quickstart.en.md`](docs/mcp_quickstart.en.md).

> The one thing that trips people up: the config needs the **absolute
> path** to `spomory-mcp` (run `which spomory-mcp` to find it) — the
> client doesn't necessarily launch it with your shell's `PATH` set.

That's it. Data lives locally in `~/.memory-core/` by default (override
with `MEMORY_CORE_DATA_DIR`). A [`Dockerfile`](Dockerfile) is also
included, for MCP directories/hosts that deploy from a container image
instead.

Want the LLM calls local too, instead of a cloud API? Point `LLM_BASE_URL`
at any local OpenAI-compatible server — vLLM, Ollama, llama.cpp, or MLX
all work — and set `EMBEDDING_PROVIDER=openai_compatible` to route
embedding the same way instead of the local `sentence-transformers`
model, dropping the `torch` dependency entirely. Details and per-engine
examples in
[`docs/mcp_quickstart.en.md`](docs/mcp_quickstart.en.md#running-fully-local-no-cloud-llm-calls-at-all).

## What it can do

Once connected, six tools become available inside the client:

| Tool | What it does |
|---|---|
| `add_memory` | Remembers something you tell it |
| `search_memory` | Recalls whatever's relevant to a question |
| `forget_memory` | Deletes the one thing that best matches what you asked to forget |
| `forget_all_memory` | Wipes the entire memory graph in one call |
| `get_graph` | Shows the memory graph around something, for inspection |
| `export_memory` | Exports everything you've stored, as JSON — your data, portable |

All six are verified working end-to-end against real Claude Desktop,
Cursor, and Codex CLI sessions, both local and remote — see
[`docs/mcp_quickstart.en.md`](docs/mcp_quickstart.en.md) for what
"verified" means for each client.

## How it works, for the curious

You don't need any of this to use Spomory — it's here for people who
want to know what's actually happening underneath.

- **Pluggable LLM / embedding providers**: defaults to any OpenAI-compatible
  API (including Chinese-market LLM providers) + local
  `sentence-transformers` (default `bge-m3`, bilingual Chinese/English).
- **Dual-layer incremental knowledge graph**: entities and relations are
  modeled as independent layers; new data is only extracted and merged in,
  never a full rebuild. Exact-match filler input ("thanks", "好的", "ok", ...)
  is skipped before it ever reaches the extraction LLM call, since it can't
  contain an extractable fact — relevant cost protection on any
  unauthenticated endpoint. Defaults to a local `LocalGraphStore`
  (networkx + SQLite); a `PostgresGraphStore` cloud implementation also
  exists, and both share the same behavioral contract test suite.
- **HippoRAG 2-style retrieval**: the query is matched directly against
  triples rather than only against entity nodes; the matched seed nodes
  are diffused via personalized PageRank for multi-hop association, then
  assembled into a natural-language context (with source timestamps, so
  "when did I mention X" is answerable). Ranking on top of that decays a
  relation's relevance the longer it's gone without being retrieved, and
  boosts it back up (log-dampened, so it can't dominate PPR rank) the more
  times the same fact has been restated — a passive signal alongside the
  active ADD/UPDATE/DELETE/NOOP decisions below.
- **Memory management**: an ADD/UPDATE/DELETE/NOOP action space, with a
  rule-based default policy (`RuleBasedPolicy`) and a full GRPO training
  pipeline (`memory_manager/train_grpo.py`, actually run and verified on
  a real GPU).
- **Memory passport export + true delete**: a JSON-LD style export format,
  physical deletion, and an audit log.
- **Multimodal image verification**: image captioning → reuses the text
  extraction pipeline → CLIP cross-checks candidate triples. Honestly
  positioned as "verification," not "native cross-modal extraction."
- **Cloud skeleton**: FastAPI user auth/API keys/quotas, a Stripe webhook
  billing scaffold (skeleton-level only, not production-deployed).

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

**LongMemEval** (`xiaowu0162/longmemeval-cleaned` oracle variant, first 10
of 500 questions):

| Metric | Value |
|---|---|
| Recall@10 | 100% (10/10) |
| Accuracy — strict substring match | 30% |
| Accuracy — LLM-judged | 80% |

The limitations here matter as much as the numbers:
1. **Only 10 questions, not the full 500** — each question ingests ~27
   turns on average (~27 real extraction calls plus one generation and one
   judge call), and this environment's LLM API calls go through a proxy
   with real latency; the full dataset would take tens of hours. This is a
   real run, not a mock, but it's a small sample and shouldn't be read as
   generalizing to the full dataset.
2. **All 10 happen to be `temporal-reasoning` type** — the dataset also has
   a `multi-session` type; `load_longmemeval(limit=10)` takes the first 10
   entries in file order with no stratified sampling, so this sample isn't
   representative of the dataset as a whole.
3. **Recall@10 = 100% is largely an artifact of the oracle variant's
   design, not a strong retrieval claim** — the oracle variant pre-filters
   each question's haystack down to only the relevant sessions (no
   distractor sessions), which is considerably easier than a real
   deployment's memory store (hundreds/thousands of unrelated turns). This
   isn't the same task as the full (non-oracle) LongMemEval benchmark and
   shouldn't be compared directly against numbers other products report on
   that harder variant.
4. Strict-match accuracy (30%) is far below LLM-judged accuracy (80%),
   consistent with the same pattern seen in the LoCoMo results — substring
   matching systematically undercounts answers that are correct but worded
   differently.

Raw data:
[`benchmarks/results/longmemeval_oracle_subset.json`](benchmarks/results/longmemeval_oracle_subset.json);
the run script is
[`benchmarks/run_longmemeval_subset.py`](benchmarks/run_longmemeval_subset.py).

## For contributors: building from source

Everything below is for people who want to hack on the internals, run
the test suite, or reach dependency groups beyond what running the MCP
server needs (GPU training, the cloud API skeleton, multimodal
verification). If you just want to use Spomory, you don't need any of
this — see "Get started" above.

### Project layout

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

### Set up a dev environment

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

### Run a minimal example (no MCP, plain Python calls)

With `dev` + `llm` + `embedding` installed and the three env vars from
"Get started" set, this script exercises the full "write a memory →
retrieve it" pipeline directly (the same logic behind
`mcp_server/server.py`'s `add_memory`/`search_memory` tools, just calling
the library directly instead of going through the MCP protocol layer):

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

### Testing

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
| [mcp_quickstart.en.md](docs/mcp_quickstart.en.md) ([中文](docs/mcp_quickstart.md)) | MCP Server install, configuration, connecting Claude Desktop/Cursor/Codex CLI, real-world gotchas |
| [graph_store_interface.en.md](docs/graph_store_interface.en.md) ([中文](docs/graph_store_interface.md)) | Storage adapter interface design |
| [export_format.en.md](docs/export_format.en.md) ([中文](docs/export_format.md)) | The "memory passport" export format |
| [dataset_format.en.md](docs/dataset_format.en.md) ([中文](docs/dataset_format.md)) | GRPO training data format and how the real dataset was generated |
| [methodology.en.md](docs/methodology.en.md) ([中文](docs/methodology.md)) | Technical methodology: what's actually verified vs. still open |
| [benchmark_smoke_test.en.md](docs/benchmark_smoke_test.en.md) ([中文](docs/benchmark_smoke_test.md)) | Real LoCoMo benchmark results and failure-case analysis |
| [memory_manager_eval.en.md](docs/memory_manager_eval.en.md) ([中文](docs/memory_manager_eval.md)) | Rule-based vs. GRPO-trained policy comparison, including the debugging process |
| [multimodal_verification.en.md](docs/multimodal_verification.en.md) ([中文](docs/multimodal_verification.md)) | Image + CLIP verification experiment results |
| [gpu_training_runbook.en.md](docs/gpu_training_runbook.en.md) ([中文](docs/gpu_training_runbook.md)) | GPU training environment setup log (including real gotchas hit) |
| [postgres_setup.en.md](docs/postgres_setup.en.md) ([中文](docs/postgres_setup.md)) | Cloud Postgres backend deployment log |
| [leaderboard_submission.en.md](docs/leaderboard_submission.en.md) ([中文](docs/leaderboard_submission.md)) | Third-party leaderboard research |
| [mvp_scope.en.md](docs/mvp_scope.en.md) ([中文](docs/mvp_scope.md)) | MVP scope definition |
| [privacy_policy_draft.en.md](docs/privacy_policy_draft.en.md) ([中文](docs/privacy_policy_draft.md)) / [product_copy_memory_passport.en.md](docs/product_copy_memory_passport.en.md) ([中文](docs/product_copy_memory_passport.md)) | Draft privacy policy / external-facing product copy |
| [eng_note_cjk_rendering_bug.en.md](docs/eng_note_cjk_rendering_bug.en.md) ([中文](docs/eng_note_cjk_rendering_bug.md)) | Engineering note: a real discover→fix→verify trace for a CJK rendering bug |

Every doc above now has both a Chinese and an English version.

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
