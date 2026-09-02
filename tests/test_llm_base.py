from memory_core.llm.base import TripleCandidate


def test_triple_candidate_roundtrip():
    triple = TripleCandidate(
        subject="张三",
        predicate="任职于",
        object="某公司",
        source_span="张三在某公司工作。",
    )
    data = triple.model_dump()
    restored = TripleCandidate(**data)
    assert restored == triple


def test_openai_compatible_requires_api_key(monkeypatch):
    pytest = __import__("pytest")
    openai = pytest.importorskip("openai")
    del openai  # only needed to skip when the `llm` extra isn't installed

    from memory_core.llm.openai_compatible import OpenAICompatibleProvider

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    try:
        OpenAICompatibleProvider()
    except KeyError as exc:
        assert "LLM_API_KEY" in str(exc)
    else:
        raise AssertionError("expected KeyError when LLM_API_KEY is unset")
