"""Text -> candidate triples extraction pipeline.

Thin wrapper over ``LLMProvider.extract_triples`` today; kept as its own
module because Epic 1.5's incremental merge logic needs a stable seam to
call into (and to swap in more elaborate chunking/prompting later without
touching callers).
"""

from __future__ import annotations

from memory_core.llm.base import LLMProvider, TripleCandidate


def extract_candidate_triples(text: str, llm: LLMProvider) -> list[TripleCandidate]:
    """Extract candidate (subject, predicate, object) triples with source spans."""
    return llm.extract_triples(text)
