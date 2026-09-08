# Product-page copy material: the "Memory Passport" (Epic 7.4)

Corresponds to the core promise of the business plan's "III. Memory
Ownership / Portability." Every sentence of the copy below has a
checkable technical basis in the code/tests -- it isn't marketing
language. This is the boundary that most needs to be held when executing
on this pillar (externally, say "a product principle we chose
proactively," never "protected under compliance with regulation X").

---

## Your memory, yours to take with you, anytime

> After the "Interim Measures for the Administration of Anthropomorphic
> AI Interactive Services" took effect in July 2026, a leading large-
> model product deleted all users' conversation history outright, with no
> migration path offered whatsoever. Your memory suddenly stopped
> belonging to you -- this isn't a hypothetical, it already happened.

We chose a different principle: **your memory can be fully exported at
any time, and completely deleted at any time -- this is a product
commitment we made proactively, not the bare minimum of compliance we
did only because a regulator required it.**

### Full export -- the "Memory Passport"

Export your complete personal knowledge graph in one action: every
entity, every relation, and every memory's source and timestamp, in an
open JSON-LD format modeled on the design approach of two early open-
standard drafts, MIF and PAM (semantic/episodic/procedural memory
classification, provenance tracking). Not a proprietary format, not
locked into our product -- an independent script can read your exported
file and reconstruct the full graph structure.

*Technical basis: `memory_core/export/schema.py` +
`docs/export_format.md`,
`tests/test_export.py::test_export_round_trips_without_information_loss`
verifies the exported file is self-consistent and loses no information.*

### True deletion -- not "out of sight, out of mind"

Click delete, and we physically purge the data from underlying storage,
rather than flagging it "deleted" while it stays in the database. You can
get a before/after record-count comparison, and you can look up the
deletion operation itself in the audit log (time, scope) -- the act of
deletion is recorded, but the deleted data itself is not.

*Technical basis: `memory_core/export/exporter.py::delete_all()`,
`tests/test_export.py::test_delete_all_is_physically_verifiable_at_the_storage_layer`
queries the underlying SQLite file directly to verify the data is
genuinely gone, not merely unreachable through the application layer;
`memory_core/audit.py` records a tamper-evident deletion audit log
(Epic 10.3).*

### These two capabilities stay on the free tier, always

Export and deletion aren't "premium features" locked behind an extra
paywall -- they're product principles, not an arbitrage tool. Putting
them behind a paywall would be an admission that "memory sovereignty" is
just marketing language.

---

## Boundaries of use (disclosed honestly)

- No authoritative standards body (W3C, IETF) currently maintains a
  formal standard for AI memory portability -- the MIF/PAM drafts we
  reference are early proposals started by individual developers, not
  yet adopted by any mainstream vendor.
- We do not claim to "comply with GDPR" or to be "protected by law" --
  this is a product principle we chose proactively, a design that gets
  ahead of regulatory trends, not an off-the-shelf compliance dividend.
