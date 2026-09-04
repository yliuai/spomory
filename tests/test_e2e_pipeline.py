"""Epic 2.4: end-to-end integration test across Epic 1 (ingest) + Epic 2 (retrieval).

Each case writes several memories (some requiring multi-hop association to
connect) via IncrementalIngestor, then asks a question and checks that the
retrieval pipeline (query_match -> PPR -> ranker) surfaces the fact needed
to answer it inside the assembled context.

This checks retrieval recall specifically, not final answer-string
generation: producing the answer text itself is `LLMProvider.generate()`'s
job, which needs a real LLM and can't be verified without API credentials
in this environment. Isolating recall this way is also the more precise
thing to test — it pinpoints failures to retrieval vs. generation instead
of conflating them behind one pass/fail per case.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.llm.base import TripleCandidate
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
from memory_core.retrieval.ranker import build_context
from tests.test_incremental import FakeLLMProvider, _triple


@dataclass
class Case:
    memories: list[list[TripleCandidate]]  # one candidate-triple list per ingested memory
    question_seed_names: list[str]  # entity names to seed PPR with (stand-in for query_match)
    expected_fact_substring: str  # text that must appear in the assembled context


CASES: list[Case] = [
    Case(
        [[_triple("张三", "任职于", "某公司")], [_triple("某公司", "报价", "报价单#88")], [_triple("报价单#88", "提到", "孩子上小学")]],
        ["张三"],
        "报价单#88提到孩子上小学",
    ),
    Case(
        [[_triple("李四", "认识", "王五")], [_triple("王五", "推荐了", "供应商A")]],
        ["李四"],
        "王五推荐了供应商A",
    ),
    Case(
        [[_triple("项目X", "负责人是", "赵六")], [_triple("赵六", "邮箱是", "zhaoliu@example.com")]],
        ["项目X"],
        "赵六邮箱是zhaoliu@example.com",
    ),
    Case(
        [[_triple("客户B", "签约于", "2025年")], [_triple("2025年", "续约条款包含", "折扣15%")]],
        ["客户B"],
        "2025年续约条款包含折扣15%",
    ),
    Case(
        [[_triple("小明", "喜欢", "咖啡")], [_triple("咖啡", "常去", "楼下咖啡馆")]],
        ["小明"],
        "咖啡常去楼下咖啡馆",
    ),
    Case(
        [[_triple("团队A", "使用", "Python")], [_triple("Python", "版本要求", "3.11+")]],
        ["团队A"],
        "Python版本要求3.11+",
    ),
    Case(
        [[_triple("会议纪要001", "参会人包括", "老板")], [_triple("老板", "关心的问题是", "上线时间")]],
        ["会议纪要001"],
        "老板关心的问题是上线时间",
    ),
    Case(
        [[_triple("供应商C", "交付周期是", "两周")], [_triple("两周", "对应违约金", "5000元")]],
        ["供应商C"],
        "两周对应违约金5000元",
    ),
    Case(
        [[_triple("合同D", "签署方是", "对方公司")], [_triple("对方公司", "联系人是", "陈经理")]],
        ["合同D"],
        "对方公司联系人是陈经理",
    ),
    Case(
        [[_triple("需求E", "提出人是", "产品经理")], [_triple("产品经理", "截止日期要求", "月底")]],
        ["需求E"],
        "产品经理截止日期要求月底",
    ),
]


def _run_case(case: Case) -> bool:
    store = LocalGraphStore(":memory:")
    for i, triples in enumerate(case.memories):
        IncrementalIngestor(store, FakeLLMProvider(triples)).ingest(f"memory {i}", source_id=f"doc-{i}")

    entities = store.all_entities()
    relations = store.all_relations()
    entities_by_id = {e.id: e for e in entities}

    seed_ids = [e.id for e in entities if e.name in case.question_seed_names]
    scores = personalized_pagerank(entities, relations, seed_entity_ids=seed_ids)
    ranked_ids = [entity_id for entity_id, _ in rank_entities(scores)]

    context = build_context(relations, entities_by_id, ranked_ids, top_k=len(entities))
    return case.expected_fact_substring in context


def test_end_to_end_recall_meets_bar():
    assert len(CASES) >= 10
    results = [_run_case(c) for c in CASES]
    passed = sum(results)
    assert passed >= 7, f"only {passed}/{len(CASES)} cases recalled the required fact"
