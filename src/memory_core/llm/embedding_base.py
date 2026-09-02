"""Pluggable embedding provider interface, same abstraction pattern as ``LLMProvider``."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class EmbeddingProvider(ABC):
    """Abstract base class every embedding backend must implement."""

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of texts, returning an (N, D) float array."""
        raise NotImplementedError
