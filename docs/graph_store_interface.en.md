# GraphStoreBase interface design notes

Corresponds to TASKS.md Epic 1.2. This note exists before any concrete
implementation, so the interface can be frozen in Phase 0 and not need a
rewrite when the storage adapter layer opens up to the community in
Phase 2 (see the business plan's "IX. Plugin Ecosystem and Openness
Strategy" -- the storage/backend adapter layer is the only architectural
layer planned to open up to third-party implementations; the retrieval
algorithms and memory-management policy stay closed).

## Interface methods

| Method | Purpose |
|---|---|
| `add_entities(entities)` | Batch insert/update entities (upsert by id) |
| `add_relations(relations)` | Batch insert/update relations (upsert by id) |
| `get_entity(entity_id)` | Look up a single entity by id |
| `find_entities_by_name(name)` | Exact name/alias lookup, used for entity disambiguation during Epic 1.5's incremental merge |
| `get_neighbors(entity_id)` | All relations where an entity is the subject or the object |
| `query_subgraph(entity_ids, hops)` | The induced subgraph within N hops of the given entities, used by Epic 2's retrieval |
| `delete_entity(entity_id)` | Physically deletes an entity and its related relations, backing Epic 7.3's "true delete" promise |
| `all_entities()` / `all_relations()` | Full export, used by Epic 7's export endpoint and benchmarks |
| `archive_relation_version(old_relation, superseded_at)` | Epic 11.7: stores a relation's content just before an UPDATE overwrites it into transaction-time history, for `relation_as_of` to query |
| `relation_as_of(relation_id, as_of)` | Epic 11.7: queries what a relation's value was at some past transaction-time point -- what the system believed then, not what it believes now |

## Design principles

1. **Only declares the minimal operation set retrieval/writes need**,
   without leaking any concrete backend's (networkx, Postgres+pgvector,
   graph database) implementation details into the interface.
2. **Writes are idempotent** (upsert by id), because Epic 1.5's
   incremental-merge logic repeatedly updates the same entity, and the
   interface shouldn't force a caller to query first to decide between
   insert and update.
3. **`delete_entity` must be a physical delete**, not a soft-delete flag
   -- this is where Epic 7.3's "true delete" promise lands at the storage
   layer, and any new backend implementation must honor it.
4. **Subgraph queries use hop count rather than a fixed depth**, leaving
   Epic 2's personalized PageRank retrieval enough room to control recall
   scope.
5. **`add_relations`'s upsert-by-id semantics don't implicitly produce
   history** -- Epic 11.7's transaction-time archiving only happens when
   the caller (the UPDATE branch in `memory_manager/actions.py`)
   explicitly decides "this is a fact correction" and separately calls
   `archive_relation_version`; `add_relations` itself never does this
   automatically. This is by design because `add_relations` is also used
   by scenarios like data migration to rewrite rows whose content hasn't
   actually changed (e.g. Epic 11.2's encryption-migration script) -- if
   the archiving logic lived inside `add_relations`, that kind of rewrite
   would be misread as "the fact changed," fabricating history that never
   actually happened.

## Known implementations

- `LocalGraphStore` (`graph/local_store.py`): a `networkx` in-memory graph
  + SQLite persistence, the Phase 0/Phase 1 local default backend. The
  `relation_history` table (Epic 11.7) reuses the same Fernet encryption
  as the main tables.
- `PostgresGraphStore` (`graph/postgres_store.py`, Epic 8.2): same
  interface, verified against a real PostgreSQL 10 instance with the full
  contract test suite (`tests/graph_store_contract.py`) and MCP Server
  functional-parity checks (`tests/test_postgres_mcp_parity.py`) -- see
  `docs/postgres_setup.md`. The `relation_history` table (Epic 11.7) is
  isolated by `user_id`, same multi-tenancy rule as the other tables.

## Transaction time vs. real-world valid time (Epic 11.7)

`relation_as_of(relation_id, as_of)` answers a **transaction-time**
question -- "what did the system believe was true at some point in time"
-- reconstructed from `Relation.valid_from` (the start of the current
value's belief window, which moves forward on every UPDATE) and the
`relation_history` table (archived old values plus the time window during
which each was in effect).

This is **not** a full bitemporal model -- a true bitemporal model also
needs **valid time**: when a fact actually became true in the real world,
which may predate when the system learned about it (e.g. "I changed jobs
in March," but the system wasn't told until September). Valid time would
need dates extracted from the source text to support, which the current
extraction pipeline (`graph/incremental.py`) doesn't do -- this is the
same gap `docs/methodology.md` section 4 calls out as "the extraction
pipeline's handling of temporal information is a real, discovered gap."
Epic 11.7 only solves the transaction-time half; this gap itself is still
open.
