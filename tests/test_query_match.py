import pytest

pytest.importorskip("sentence_transformers")

from memory_core.graph.models import Entity, Relation
from memory_core.retrieval.query_match import _strip_folded_date, match_query_to_triples


@pytest.fixture(autouse=True)
def _small_multilingual_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")


def test_strip_folded_date_removes_only_the_date_fragment():
    """Regression test for the Recall@10 drop root-caused in
    docs/benchmark_smoke_test.md: folding a date into the predicate (the
    extraction prompt's date-into-predicate trick) shifted its embedding
    enough to move retrieval rankings for reasons unrelated to relevance.
    _strip_folded_date is used only when building the text embedded for
    matching -- the date-carrying predicate stored on the relation, and
    what ranker.py renders, are untouched.
    """
    assert _strip_folded_date("在2023年5月7日去了") == "去了"
    assert _strip_folded_date("went to on 2023-05-07") == "went to"
    # No folded date present -> returned unchanged (not even whitespace-trimmed
    # away to nothing, and no accidental match on an unrelated date-shaped
    # substring inside a longer predicate).
    assert _strip_folded_date("任职于") == "任职于"
    assert _strip_folded_date("recommended") == "recommended"


@pytest.mark.slow
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
