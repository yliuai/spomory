import pytest

pytest.importorskip("sentence_transformers")

from memory_core.graph.models import Entity, Relation
from memory_core.retrieval.query_match import match_query_to_triples


@pytest.fixture(autouse=True)
def _small_multilingual_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")


def test_recalls_correct_multi_hop_triple_for_paraphrased_query():
    from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider

    zhangsan = Entity(name="张三", type="person")
    quote = Entity(name="报价单#88", type="document")
    kid_fact = Entity(name="孩子今年上小学", type="fact")
    weather = Entity(name="天气", type="topic")
    entities_by_id = {e.id: e for e in [zhangsan, quote, kid_fact, weather]}

    relations = [
        Relation(subject_id=zhangsan.id, predicate="提到了报价单", object_id=quote.id),
        Relation(subject_id=zhangsan.id, predicate="提到了", object_id=kid_fact.id),
        Relation(subject_id=zhangsan.id, predicate="聊到了", object_id=weather.id),
    ]

    embedder = SentenceTransformerProvider()
    # Paraphrased query: doesn't share exact wording with any relation, but is
    # semantically about "did he mention his kid" — the correct triple to recall
    # is (张三, 提到了, 孩子今年上小学), not the report or the weather chit-chat.
    matches = match_query_to_triples(
        "张三聊天时有没有说起他家小孩的事？",
        relations,
        entities_by_id,
        embedder,
        top_k=1,
    )

    assert matches[0].relation.object_id == kid_fact.id
