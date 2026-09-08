# Memory export format (the "Memory Passport")

Corresponds to TASKS.md Epic 7.1/7.2. This is the engineering-level
implementation of the "Memory Passport" promise from the business plan's
"III. Memory Ownership / Portability" chapter: a user can export their
complete personal knowledge graph at any time, in a self-contained format
that loses no information and can be parsed by an independent script
without depending on this product's own code.

## Design references

Draws on the design ideas behind two early drafts, MIF (Memory
Interchange Format) and PAM (Portable AI Memory), without copying either
wholesale (both are still v0.1-level personal-project drafts that no
mainstream vendor has adopted):

- **Semantic/episodic/procedural memory classification**: every
  entity/relation carries a `memory_type` field (`semantic` / `episodic`
  / `procedural`). In the current implementation, newly extracted memory
  defaults to `semantic` (declarative facts); automatic classification of
  episodic memory ("what happened in a given conversation") and
  procedural memory ("the user's behavioral habits") is left for
  refinement once Epic 3's memory manager is wired in.
- **Provenance tracking**: modeled on W3C PROV-O's approach (without
  copying the full spec), each `provenance` record carries `source_id`
  (the source document/conversation id), `source_span` (the verbatim
  source text snippet), and `extractor` (the extraction pipeline's name +
  version).
- **JSON-LD structured data**: the top level declares a vocabulary and
  document type via `@context`/`@type`, so the exported file can be
  understood by generic JSON-LD tooling even without this project's code.

## Schema

`memory_core/export/schema.py` defines `MemoryExport`:

```
{
  "@context": {...},                 # JSON-LD vocabulary
  "@type": "memory:MemoryPassport",
  "exported_at": "<ISO8601 UTC>",
  "subject_id": "<user id>",
  "entities": [
    {
      "id": "...", "name": "...", "type": "...", "memory_type": "semantic",
      "attributes": {...}, "aliases": [...],
      "provenance": [{"source_id": "...", "source_span": "...", "extractor": "..."}],
      "created_at": "...", "updated_at": "..."
    }
  ],
  "relations": [
    {
      "id": "...", "subject_id": "...", "predicate": "...", "object_id": "...",
      "confidence": 0.95, "memory_type": "semantic",
      "provenance": [...], "created_at": "...", "updated_at": "..."
    }
  ]
}
```

See the full example at
[`examples/memory_passport_sample.json`](examples/memory_passport_sample.json).

## Self-consistency verification

`tests/test_export.py::test_export_round_trips_without_information_loss`
verifies: every `relation`'s `subject_id`/`object_id` can be found in the
`entities` list -- an independent script can reconstruct the full graph
structure from the export file alone, with no access to the original
database needed.

## True deletion

`memory_core/export/exporter.py`'s `delete_all()` implements Epic 7.3's
"the right to delete means true deletion" promise: it physically deletes
records in the underlying storage (SQLite) and returns a
`DeletionReceipt` (a before/after comparison of entity/relation counts).
`tests/test_export.py::test_delete_all_is_physically_verifiable_at_the_storage_layer`
queries the SQLite file itself directly (bypassing the application layer)
to confirm the data is actually physically gone, not merely unreachable
through the application layer -- this is a direct response to the
negative case reported against Tongyi Qianwen ("deletion means total,
unrecoverable loss with no migration path"): the right to delete must
likewise be a verifiable true deletion, not a soft-delete flag.
