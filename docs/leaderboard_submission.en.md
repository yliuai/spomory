# Epic 4.5: third-party leaderboard research

## Conclusion: the Agent Memory Leaderboard is still active, but this repo can't submit at this stage

Research date: 2026-09-03.

## Current state (real research findings, not guesses)

The Agent Memory Leaderboard (AML) mentioned in the business plan **is
still actively maintained**:

- Launched by 20+ universities/research institutions on July 29, 2026,
  with the "Agent Memory Challenge 2026" currently underway, accepting
  submissions from both open-source and commercial memory systems.
- The first round has already reviewed 136+ memory systems, with results
  announced on August 12; the first round's submission deadline was
  August 7, 2026 (this repo missed that window).
- **The second round is expected to open September 20, 2026**, after
  which new system submissions will be accepted on an ongoing basis.
- Official site: `agentmemoryleaderboard.ai`; repo:
  `AML-memory/agent-memory-leaderboard`.

## Submission requirements

1. The system must expose publicly accessible **Add** and **Search**
   endpoints (HTTP API) -- the platform itself handles answer generation,
   evaluation, scoring, and the batch pipeline; the entrant is only
   responsible for the "memory" layer.
2. Apply for evaluation eligibility via
   `agentmemoryleaderboard.ai/evaluation`; after getting an AML key, run
   a compatibility smoke test first, then the full evaluation suite.
3. Split into open-source and commercial categories: the open-source
   category requires public code, configuration, and reproducibility
   materials.
4. Results are scored 0-100; kept private until evaluation completes, and
   only listed after passing review.

## Why it can't be submitted at this stage

Checking against the requirements one by one, what this repo is currently
missing is:

- **No publicly accessible Add/Search HTTP endpoints** -- right now there
  is only the local MCP Server (stdio protocol, via Claude Desktop/
  Cursor), not the public HTTP service AML requires. This falls under
  Epic 8 (the cloud FastAPI service); Epic 8.1 only built the auth/quota
  shell, and hasn't yet wrapped Epic 1/2's memory read/write capability
  as public API endpoints.
- **Epic 4.2's required formal full-pipeline benchmark run hasn't been
  done yet** -- there's currently only the small 6-QA-pair subset result
  recorded by Epic 4.3 (see `docs/benchmark_smoke_test.md`), far short of
  the formal-benchmark bar of "100+ samples run, publishable."

## Next steps (concrete action items, not vague suggestions)

1. Add two endpoints on top of Epic 8.1's FastAPI shell: `POST
   /memory/add`, `POST /memory/search`, directly reusing the already-
   working, real-LLM-verified logic in `IncrementalIngestor` and
   `retrieval/` -- not much extra work, since the core algorithms are
   already in place.
2. Deploy those two endpoints to a publicly reachable address (this repo
   currently has no cloud deployment; this step needs an actual server/
   hosting environment).
3. Fill in Epic 4.2's formal benchmark run (100+ samples, real metrics),
   as the internal baseline reference before submitting.
4. Apply for evaluation eligibility via
   `agentmemoryleaderboard.ai/evaluation` in time for the second round's
   opening window on September 20, 2026.

## An alternative credibility path if the leaderboard window is ultimately missed

The business plan has already laid out an alternative path that doesn't
depend on this one leaderboard: write up the 4.1/4.2 methodology and
results as a technical blog post/preprint (Epic 4.4), and keep the open-
source repo itself reproducible (README + thorough test coverage) --
neither of these depends on whether AML's second round opens on
schedule.
