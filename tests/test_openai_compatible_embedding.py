"""Tests for OpenAICompatibleEmbeddingProvider -- the embedding path used
by fully-local deployments that run vLLM/Ollama/llama.cpp/MLX instead of
sentence-transformers. The construction test always runs; the real-call
test is marked slow and needs an actual OpenAI-compatible embeddings
server reachable at EMBEDDING_BASE_URL (e.g. `ollama serve` +
`ollama pull nomic-embed-text`), skipped otherwise -- this mirrors how
test_e2e_real_llm.py is gated on a real LLM_API_KEY rather than mocked.
"""

from __future__ import annotations

import os

import pytest


def test_defaults_to_llm_base_url_and_api_key(monkeypatch):
    pytest.importorskip("openai")

    monkeypatch.setenv("LLM_API_KEY", "sk-shared")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)

    from memory_core.llm.openai_compatible_embedding import OpenAICompatibleEmbeddingProvider

    provider = OpenAICompatibleEmbeddingProvider()
    assert provider.api_key == "sk-shared"
    assert provider.base_url == "http://localhost:9999/v1"


def test_embedding_specific_env_vars_override_the_llm_ones(monkeypatch):
    pytest.importorskip("openai")

    monkeypatch.setenv("LLM_API_KEY", "sk-shared")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-embedding-only")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1")

    from memory_core.llm.openai_compatible_embedding import OpenAICompatibleEmbeddingProvider

    provider = OpenAICompatibleEmbeddingProvider()
    assert provider.api_key == "sk-embedding-only"
    assert provider.base_url == "http://localhost:8000/v1"


def test_falls_back_to_placeholder_api_key_when_nothing_is_set(monkeypatch):
    pytest.importorskip("openai")

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    from memory_core.llm.openai_compatible_embedding import OpenAICompatibleEmbeddingProvider

    provider = OpenAICompatibleEmbeddingProvider(base_url="http://localhost:11434/v1")
    assert provider.api_key == "not-needed"


@pytest.mark.slow
def test_real_local_server_matching_texts_more_similar_than_unrelated():
    pytest.importorskip("openai")
    base_url = os.environ.get("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

    import httpx

    try:
        httpx.get(base_url.rsplit("/v1", 1)[0] or "http://localhost:11434", timeout=2)
    except httpx.HTTPError:
        pytest.skip(f"no OpenAI-compatible embeddings server reachable at {base_url}")

    import numpy as np

    from memory_core.llm.openai_compatible_embedding import OpenAICompatibleEmbeddingProvider

    provider = OpenAICompatibleEmbeddingProvider(base_url=base_url, model=model)
    texts = [
        "I love hiking in the mountains on weekends.",
        "Hiking in the mountains every weekend is my favorite hobby.",
        "The quarterly earnings report exceeded analyst expectations.",
    ]
    vectors = provider.embed(texts)
    assert vectors.shape[0] == 3

    def cos_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    matching = cos_sim(vectors[0], vectors[1])
    unrelated = cos_sim(vectors[0], vectors[2])
    assert matching > unrelated
