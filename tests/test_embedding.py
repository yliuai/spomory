
import pytest

pytest.importorskip("sentence_transformers")

import numpy as np


@pytest.fixture(autouse=True)
def _small_multilingual_model(monkeypatch):
    # Use a much smaller multilingual model than the production default (bge-m3)
    # so this test downloads quickly; the abstraction under test is identical.
    monkeypatch.setenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")


def test_cross_lingual_similarity_higher_for_matching_meaning():
    from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider

    provider = SentenceTransformerProvider()
    texts = [
        "今天天气很好，适合出去散步。",  # zh: nice weather, good for a walk
        "The weather is great today, perfect for a walk.",  # matching en
        "The stock market crashed sharply this morning.",  # unrelated en
    ]
    vectors = provider.embed(texts)
    assert vectors.shape[0] == 3

    def cos_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    matching = cos_sim(vectors[0], vectors[1])
    unrelated = cos_sim(vectors[0], vectors[2])
    assert matching > unrelated
