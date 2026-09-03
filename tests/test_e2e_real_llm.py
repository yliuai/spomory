"""Epic 2.4, run against a real LLM + real embedding model end to end.

Skipped unless LLM_API_KEY is set (costs real API calls) — this is the
"real" counterpart to test_e2e_pipeline.py's offline recall-only proxy:
here every stage (extraction, query->triple matching, PPR, generation) uses
the real providers, and correctness is judged on the final generated
answer text, matching Epic 2.4's acceptance criterion literally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

pytest.importorskip("openai")
pytest.importorskip("sentence_transformers")

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"), reason="requires a real LLM_API_KEY"
)


@dataclass
class Case:
    memories: list[str]
    question: str
    expected_answer_substring: str


CASES: list[Case] = [
    Case(["张三在某公司工作。", "某公司最近报价了报价单#88。", "报价单#88里提到孩子上小学。"],
         "张三聊报价单的时候有没有提到孩子上学的事？", "小学"),
    Case(["李四认识王五。", "王五推荐了供应商A。"], "王五推荐了哪个供应商？", "供应商A"),
    Case(["项目X的负责人是赵六。", "赵六的邮箱是zhaoliu@example.com。"], "项目X负责人的邮箱是什么？", "zhaoliu@example.com"),
    Case(["客户B在2025年签约。", "2025年的续约条款包含15%的折扣。"], "客户B的续约条款折扣是多少？", "15"),
    Case(["小明喜欢喝咖啡。", "他常去楼下的咖啡馆喝咖啡。"], "小明喜欢去哪里喝咖啡？", "楼下"),
    Case(["团队A使用Python。", "Python的版本要求是3.11以上。"], "团队A用的Python版本要求是多少？", "3.11"),
    Case(["会议纪要001的参会人包括老板。", "老板关心的问题是上线时间。"], "老板在会上关心什么问题？", "上线时间"),
    Case(["供应商C的交付周期是两周。", "两周交付对应的违约金是5000元。"], "供应商C两周交付的违约金是多少？", "5000"),
    Case(["合同D的签署方是对方公司。", "对方公司的联系人是陈经理。"], "合同D对方公司的联系人是谁？", "陈经理"),
    Case(["需求E的提出人是产品经理。", "产品经理要求截止日期是月底。"], "需求E的截止日期要求是什么时候？", "月底"),
]


def _run_case(case: Case, llm, embedder) -> bool:
    from memory_core.graph.incremental import IncrementalIngestor
    from memory_core.graph.local_store import LocalGraphStore
    from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
    from memory_core.retrieval.query_match import match_query_to_triples
    from memory_core.retrieval.ranker import build_context

    store = LocalGraphStore(":memory:")
    ingestor = IncrementalIngestor(store, llm)
    for i, text in enumerate(case.memories):
        ingestor.ingest(text, source_id=f"doc-{i}")

    entities = store.all_entities()
    relations = store.all_relations()
    entities_by_id = {e.id: e for e in entities}
    if not relations:
        return False

    matches = match_query_to_triples(case.question, relations, entities_by_id, embedder, top_k=5)
    seed_ids = {m.relation.subject_id for m in matches} | {m.relation.object_id for m in matches}
    scores = personalized_pagerank(entities, relations, seed_entity_ids=list(seed_ids))
    ranked_ids = [entity_id for entity_id, _ in rank_entities(scores)]
    context = build_context(relations, entities_by_id, ranked_ids, top_k=len(entities))

    prompt = f"根据以下背景信息回答问题，只输出答案本身，不要解释。\n背景：{context}\n问题：{case.question}"
    answer = llm.generate(prompt)
    return case.expected_answer_substring in answer


@pytest.mark.slow
def test_end_to_end_real_llm_answers_meet_bar():
    from memory_core.llm.local_sentence_transformer import SentenceTransformerProvider
    from memory_core.llm.openai_compatible import OpenAICompatibleProvider

    os.environ.setdefault("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    llm = OpenAICompatibleProvider()
    embedder = SentenceTransformerProvider()

    results = [_run_case(c, llm, embedder) for c in CASES]
    passed = sum(results)
    assert passed >= 7, f"only {passed}/{len(CASES)} cases answered correctly: {results}"
