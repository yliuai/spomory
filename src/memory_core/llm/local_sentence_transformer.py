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
    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
        self._model = SentenceTransformer(self.model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, normalize_embeddings=True))
