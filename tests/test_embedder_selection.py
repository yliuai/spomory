import pytest

pytest.importorskip("mcp")


def test_defaults_to_sentence_transformers(monkeypatch):
    from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
    from memory_core.mcp_server.server import _select_embedder_from_env

    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)

    embedder = _select_embedder_from_env()
    assert isinstance(embedder, SentenceTransformerProvider)


def test_openai_compatible_selected_explicitly(monkeypatch):
    pytest.importorskip("openai")
    from memory_core.llm.openai_compatible_embedding import OpenAICompatibleEmbeddingProvider
    from memory_core.mcp_server.server import _select_embedder_from_env

    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai_compatible")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")

    embedder = _select_embedder_from_env()
    assert isinstance(embedder, OpenAICompatibleEmbeddingProvider)


def test_unknown_provider_raises(monkeypatch):
    from memory_core.mcp_server.server import _select_embedder_from_env

    monkeypatch.setenv("EMBEDDING_PROVIDER", "something-made-up")

    with pytest.raises(ValueError, match="something-made-up"):
        _select_embedder_from_env()
