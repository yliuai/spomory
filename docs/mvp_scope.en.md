# Minimal MVP scope (Epic 9.1)

Corresponds to the business plan's "V. Target Users and Cold-Start
Playbook": rather than targeting a broad general-audience personal-
memory persona directly, narrow first to one specific professional-
knowledge-worker vertical.

## Target users

Technical consultants / software engineers / independent developers --
people who already need to manage a lot of projects, clients, and
technical knowledge, have high tolerance for new tools, and have short
decision chains. The first batch of seed users comes preferentially from
communities the founder's own software-engineering background can
naturally reach.

## Core use case

Continuously feed project notes, client communication records, and
technical documentation into a personal knowledge graph, which can then
be retrieved and called on by agents inside Claude Code / Cursor -- this
isn't a standalone memory app, it's making those tools "remember" the
user's past project context within a conversation.

## What's in scope

1. **MCP Server** (Epic 6): four tools -- `add_memory` / `search_memory`
   / `get_graph` / `export_memory` -- connected to Claude Desktop / Cursor.
2. **Bulk import** (Epic 9.2, implemented, see `memory_core/onboarding.py`):
   one-time import of an existing folder of Markdown/plain-text notes
   into the graph.
3. **Local-first**: `LocalGraphStore` (SQLite) by default, with no forced
   cloud account registration required to get started.
4. **Memory-passport export/true deletion** (Epic 7, implemented): a
   free-tier capability, not a marketing gimmick.

## Explicitly out of scope (at this stage)

- **No general-audience consumer UI** -- no standalone chat-style app/web
  product; only the developer tool and the clients it connects to
  (Claude Desktop/Cursor).
- **No PDF/voice/image import** -- Epic 9.2 only supports Markdown/plain
  text; PDF is deferred, voice/image fall under Epic 5 (multimodal) and
  aren't invested in at this stage.
- **No browser extension** -- a cross-platform extension covering
  consumer web endpoints like ChatGPT/Gemini is a Phase 2 concern
  (corresponding to Part IV of the business plan); the MVP stage only
  covers the developer clients MCP reaches.
- **No team edition/multi-user collaboration** -- single-user personal
  memory graph; permission models and sharing/collaboration are deferred
  until personal-edition retention is validated (corresponding to the
  business plan's Phase 3 branch decision).
- **No full billing system** -- Epic 8.1/8.3 only built the auth+quota
  shell; actually launching paid billing requires a signal of willingness
  to pay before investing in full Stripe integration.

## Success signals (echoing the business plan's Phase 1 success metrics)

The first seed users' second-month retention, initial paid-conversion
rate, NPS/qualitative interview signals -- not feature count.

---

## Epic 11.6: ICP reconfirmation (2026-09, based on competitive analysis)

Epic 9.1's "technical consultants/engineers" vertical was a narrowing for
the MVP stage. Epic 11.6, based on an analysis of seven competitors
including MemoryPlugin/Mnemoverse/Mem0 (see the internal strategy
document "Spomory Competitive Analysis"), redoes that choice across
three candidate directions:

1. A local-first memory engine for developers/tech enthusiasts
2. Consumer cross-app memory
3. Enterprise memory governance

**Decision: invest in Direction 1 + Direction 2 together, and hold off on
Direction 3 for now, revisiting whether it's worth doing once the first
two show validated signal (retention, paid conversion).**

### Why these two together, rather than picking one of three

Direction 1 (developer local-first) isn't a brand-new direction -- it's a
continuation and confirmation of Epic 9.1's conclusion. The first batch
of seed users, the local stdio access path in `docs/mcp_quickstart.md`,
and the "memory passport" true-delete capability are all things already
built; the value proposition hasn't changed.

Direction 2 (consumer cross-app memory) is the genuinely new scope this
time: the existing local edition can only be used by clients like Claude
Desktop/Cursor that can spawn a local subprocess, and doesn't reach
mobile apps or web-based ChatGPT/Gemini -- scenarios where a local
environment can't be installed at all. That exact user base happens to be
the most direct audience for "memory needs to work across multiple
apps." These two directions actually correspond to the same core
capability (memory-graph extraction/retrieval/management) presented
through two different distribution forms, not two separate products --
the investment doesn't conflict.

Direction 3 (enterprise memory governance) isn't invested in for now,
because what it needs (multi-user collaboration, a permission model, SSO,
compliance-facing audit capability) shares almost nothing with the first
two directions -- `docs/mvp_scope.md`'s "explicitly out of scope" item
"no team edition/multi-user collaboration" still holds; whether it's
worth a dedicated product line will be revisited once Directions 1/2
validate real willingness to pay.

### Impact on Epic 11.5 (the remote MCP service)

This decision elevates the remote service's role from "an optional
second access method / a prerequisite for listing on various MCP
marketplaces" to "the core product form for Direction 2's users" -- the
local stdio edition satisfies Direction 1, but Direction 2 (consumer
cross-app) users inherently need a memory backend that doesn't depend on
a local environment and can be reached by multiple apps at once, which is
exactly what `src/memory_core/mcp_server/remote.py` + `src/cloud_api/`
are already building. This also echoes an earlier discussion about
whether the local edition is still worth keeping: Direction 1 users keep
using the local edition (free, privacy-first, a zero-infrastructure-cost
acquisition channel), Direction 2 users use the remote edition (account +
cloud storage) -- the two lines serve different user groups, not a
replacement relationship.

### Impact on pricing

`src/cloud_api/billing.py`'s existing free/weekly/monthly/annual tiered
pricing (avoiding the problem of Mem0's 13x jump from $19 to $249) is
designed for individual developers/consumers, and applies directly to
both Direction 1 and 2 -- there's no need to design enterprise contract
pricing (per-seat billing, SSO add-on fees, etc.) right now just for
Direction 3. That work is deferred until Direction 3 is actually
activated; doing it now would only add complexity with no corresponding
paying users to validate it against.
