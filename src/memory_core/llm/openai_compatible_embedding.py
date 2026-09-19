"""Embedding provider that talks to any OpenAI-compatible `/v1/embeddings`
endpoint -- vLLM, Ollama, and llama.cpp's `llama-server --embedding` all
expose this same protocol, and as of 2026 so does the MLX ecosystem
(`mlx_lm.server`'s built-in support, plus community servers like
vllm-mlx and mlx-openai-server). One implementation covers all four
engines, the same way `OpenAICompatibleProvider` already covers all four
for chat/extraction.

Unlike `SentenceTransformerProvider`, this needs no local ML framework
installed at all -- no `sentence-transformers`, no `torch` -- since the
actual embedding computation happens wherever the pointed-at server runs.
Picking this provider (`EMBEDDING_PROVIDER=openai_compatible`) is how a
fully-local deployment avoids that dependency weight entirely when an
inference engine is already running for LLM extraction anyway.
"""

from __future__ import annotations

import os

import numpy as np

from .embedding_base import EmbeddingProvider

DEFAULT_MODEL_NAME = "bge-m3"


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        from openai import OpenAI

        # Local inference servers (Ollama, llama.cpp, vLLM, MLX) generally
        # don't validate the API key at all, but the `openai` SDK still
        # requires a non-empty string -- "not-needed" is the placeholder
        # convention most local-LLM setups already use.
        self.api_key = (
            api_key
            or os.environ.get("EMBEDDING_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or "not-needed"
        )
        # Falls back to LLM_BASE_URL: a single Ollama server commonly hosts
        # both the chat model and the embedding model on the same port,
        # distinguished only by the `model` field per request. vLLM and
        # llama.cpp usually serve one model per process, so a setup using
        # either for embeddings will typically set EMBEDDING_BASE_URL to a
        # second port explicitly.
        self.base_url = base_url or os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("LLM_BASE_URL")
        self.model = model or os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def embed(self, texts: list[str]) -> np.ndarray:
        response = self._client.embeddings.create(model=self.model, input=texts)
        # The API contract doesn't guarantee response order matches input
        # order -- sort by each item's own `index` field rather than trust
        # list position.
        by_index = sorted(response.data, key=lambda item: item.index)
        return np.asarray([item.embedding for item in by_index])
