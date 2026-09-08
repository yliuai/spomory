## Spomory

An explainable graph-retrieval memory engine, exposed via MCP to Claude Desktop, Cursor, and other clients for persistent long-term memory.

**Core approach**: HippoRAG-style retrieval (query→triple matching + personalized PageRank diffusion) + a LightRAG-style incremental knowledge graph (only new text is processed, never a full rebuild) + a GRPO-trained memory-management policy — not hardcoded add/delete rules, but a trained model deciding when to ADD, UPDATE, DELETE, or NOOP a fact.

**Five MCP tools**:
- `add_memory` — extract facts from text and write them into the memory graph
- `search_memory` — retrieve and assemble relevant context via graph traversal
- `forget_memory` — permanently delete a single matched fact (true delete, not a soft flag)
- `get_graph` — inspect the subgraph around an entity; every retrieval result traces back to a specific triple, not just a similarity score
- `export_memory` — export the full memory graph as a JSON "memory passport"

**Deployment**: run locally (data stays in an encrypted-by-default SQLite file on your machine) or connect to the hosted remote server (multi-tenant Postgres, with both API-key and OAuth 2.1 authentication).

Measured LoCoMo/LongMemEval benchmark results — including their limitations — are published in the [GitHub README](https://github.com/yliuai/spomory).
