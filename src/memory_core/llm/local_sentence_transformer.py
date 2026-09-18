"""Default embedding provider: a local sentence-transformers model.

Defaults to a multilingual model so Chinese and English text land in the
same embedding space, per the product's bilingual requirement.
"""

from __future__ import annotations

import os

import numpy as np

from .embedding_base import EmbeddingProvider

DEFAULT_MODEL_NAME = "BAAI/bge-m3"


class SentenceTransformerProvider(EmbeddingProvider):
    """Loads its model lazily, on the first `embed()` call, rather than in
    `__init__`: constructing this class runs at MCP server startup, and
    eagerly loading a multi-GB multilingual model there blocks the process
    for several seconds before it can respond to anything -- including a
    health-check ping, which some hosts (e.g. Glama's container deploy)
    time out and kill before the server ever comes up."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._get_model().encode(texts, normalize_embeddings=True))
