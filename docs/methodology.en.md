# Methodology draft: HippoRAG-style retrieval + LightRAG-style incremental graph + GRPO memory management (Epic 4.4)

> A draft aimed at a future paper submission/technical blog post. The
> goal is to lay out this combination's design rationale, along with
> which conclusions the current measurements can and can't support --
> per Epic 4's requirement, the two are honestly kept separate.

## 1. Problem setting

The data characteristics of personal-memory scenarios differ from
typical RAG scenarios: **continuous, small-increment growth**, rather
than a one-time bulk-corpus indexing job. That means the selection
criterion for an indexing scheme is different too -- not "highest
possible retrieval quality," but "retrieval quality that's good enough +
a controllable indexing cost for each new increment of data." This is
the direct motivation behind this plan's choice to move away from
GraphRAG (expensive indexing, rebuilds the whole graph on every update)
and toward a LightRAG-style incremental graph instead.

## 2. System design

### 2.1 Storage layer: a two-layer incremental graph

`graph/models.py` models `Entity`/`Relation` as independent layers
(entity layer, relation layer); `graph/incremental.py`'s
`IncrementalIngestor` processes only newly added text on each call:
extract candidate triples → disambiguate entities via exact name/alias
matching (conservatively creating a new entity on ambiguity, to avoid
falsely merging two distinct same-named entities) → write only the
new/updated nodes and edges, without rebuilding the whole graph.

### 2.2 Retrieval layer: query→triple matching + personalized PageRank

Modeled on HippoRAG 2's approach, `retrieval/query_match.py` matches the
query directly against triples' natural-language rendering via embedding
similarity (rather than matching only to entity nodes), then uses the
matched triples' endpoints as seeds for a one-shot diffusion via
`retrieval/ppr.py` (`networkx.pagerank`'s personalization parameter),
in place of hop-by-hop iterative RAG.

### 2.3 Memory-management layer: GRPO trains a policy that decides what to remember/forget/update

`memory_manager/actions.py` defines the ADD/UPDATE/DELETE/NOOP action
space; `memory_manager/reward.py` uses a single result-oriented reward
based on downstream QA correctness (compared to Mem-α's four-part reward,
this is a better fit for a resource-constrained team just starting out);
`memory_manager/train_grpo.py` trains with TRL's GRPOTrainer + PEFT LoRA.

## 3. Measured results: conclusions currently supported

| Verification item | Result | Method |
|---|---|---|
| The triple-extraction pipeline runs end-to-end against a real LLM | A test passage extracted 3/3 reasonable triples | Real DeepSeek API call |
| The embedding layer distinguishes semantically close/unrelated sentences in Chinese and English | Semantically close sentences have noticeably higher cosine similarity | Real local multilingual embedding model |
| Query→triple matching recalls the correct path when it requires cross-entity association | Reproduced HippoRAG 2's design intent of "not matching only to nodes" | Real embeddings, hand-constructed multi-hop test cases |
| PPR diffusion recalls nodes 3 hops away, ranked ahead of unrelated nodes | Verified on a hand-constructed test graph with 20+ nodes | Unit test (deterministic graph structure, not model-dependent) |
| Incremental writes don't degrade unacceptably as the graph grows | A single incremental write on a 2,000+-node graph takes < 2 seconds | Unit test benchmark |
| The end-to-end pipeline (extraction + retrieval + generation) correctly answers questions requiring relational reasoning | 10 hand-constructed multi-hop questions, run through the full pipeline with a real LLM + embeddings, ≥7/10 correct | Real LLM call (`tests/test_e2e_real_llm.py`) |
| The GRPO training script's engineering pipeline (data → LoRA → training loop) runs end-to-end | Completed a training loop on a placeholder small model, with real reward/loss output | Real TRL/PEFT training loop (placeholder model, not production-grade) |

## 4. Measured results: conclusions not yet supported (stated honestly, not glossed over)

- **"HippoRAG-style PPR beats plain vector retrieval" isn't backed by
  enough samples yet**: on a tiny 6-QA-pair subset of the LoCoMo dataset,
  the PPR version scored 83% recall@10 versus 67% for the plain-vector
  baseline (see `docs/benchmark_smoke_test.md`) -- directionally
  consistent with the HippoRAG paper's claim, but n=6 is far too small
  for a statistically significant conclusion.
- **GRPO training's actual improvement to the memory-management policy
  hasn't been verified yet**: `train_grpo.py`'s training loop itself runs
  end-to-end, but it used a placeholder small model and toy data, not a
  real 7-8B model + the 150 real labeled samples Epic 3.1 calls for. The
  rule-based baseline (`RuleBasedPolicy`) is implemented and tested, but
  the comparison against an actually-trained policy (Epic 3.6) couldn't
  be done yet because there was no trained checkpoint to compare against.
- **The extraction pipeline's handling of temporal information is a
  real, discovered gap**: in small-sample testing, temporal questions
  ("when did...") were systematically unanswerable, and the root cause is
  that triple extraction doesn't systematically carry the
  conversation/document's occurrence time into the triples or provenance
  -- this is a specific problem to fix next, not a vague "not good
  enough" verdict.

## 5. Limitations and next steps

This document honestly records what could be verified within the
development environment available (higher network latency, no GPU
cluster, no cloud deployment). To turn the open questions in section 4
into the verified conclusions of section 3, the concrete next steps are:

1. A lower-latency network environment or batched-call optimization, to
   run the full 100+-sample formal benchmark Epic 4.1/4.2 calls for (the
   current 20-turn conversation + 6 QA pairs already takes ~3-5 minutes).
2. Carry timestamp information into the extraction pipeline
   (`graph/extract.py`/`graph/incremental.py`), then rerun the benchmark
   to verify whether this fixes the systematic failure on temporal
   questions.
3. Run Epic 3.4's GRPO training with a real GPU budget (a 7-8B model, 150
   real labeled samples), which is needed before Epic 3.6's rule-based
   vs. trained-policy comparison can happen.
4. Add public Add/Search endpoints on top of Epic 8.1's skeleton, which
   is a prerequisite for submitting to the Agent Memory Leaderboard
   (Epic 4.5, whose second round is expected to open 2026-09-20).
