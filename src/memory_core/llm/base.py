"""Pluggable LLM provider interface.

Keeping this layer abstract means swapping to a different model vendor
(e.g. a domestic provider like Qwen/Zhipu/DeepSeek) later only requires
adding a new ``LLMProvider`` implementation, not touching call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class TripleCandidate(BaseModel):
    """A single (subject, predicate, object) candidate extracted from text."""

    subject: str
    predicate: str
    object: str
    source_span: str = Field(description="Verbatim text snippet the triple was extracted from")


class LLMProvider(ABC):
    """Abstract base class every LLM backend must implement."""

    @abstractmethod
    def extract_triples(self, text: str) -> list[TripleCandidate]:
        """Extract candidate (subject, predicate, object) triples from ``text``."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str, **kwargs: object) -> str:
        """Generate free-form text for ``prompt``."""
        raise NotImplementedError
