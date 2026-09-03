"""Epic 4.1: write memories -> retrieve -> generate an answer -> score against
the gold answer, for one conversation from a benchmark dataset.

Recall@K is computed against the retrieval step in isolation (did the
correct evidence turn make it into the top-K context), and accuracy is
computed against the final generated answer — deliberately kept as two
separate numbers rather than one blended score, so a regression can be
traced to retrieval or to generation instead of just "the number went
down."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.llm.base import LLMProvider
from memory_core.llm.embedding_base import EmbeddingProvider
from memory_core.retrieval.ppr import personalized_pagerank, rank_entities
from memory_core.retrieval.query_match import match_query_to_triples
from memory_core.retrieval.ranker import build_context

from .loaders import Conversation, QAPair


class AnswerScorer(Protocol):
    def __call__(self, predicted: str, gold: str) -> bool: ...


def exact_or_substring_match(predicted: str, gold: str) -> bool:
    predicted, gold = predicted.strip().lower(), gold.strip().lower()
    return gold != "" and (gold in predicted or predicted == gold)


def make_llm_judge_scorer(llm: LLMProvider) -> AnswerScorer:
    """A looser scorer for free-text answers where wording legitimately
    varies (e.g. "Psychology, counseling certification" vs "Counseling and
    mental health fields" should both count as correct). Costs one extra
    LLM call per QA pair, so it's opt-in rather than the default.
    """

    def judge(predicted: str, gold: str) -> bool:
        if not gold.strip():
            return False
        prompt = (
            "判断【模型答案】是否在语义上正确回答了问题、且与【标准答案】一致"
            "（措辞不同但意思相同也算正确；模型答案说不知道/未提及则算错误）。"
            f"只回答 YES 或 NO。\n标准答案：{gold}\n模型答案：{predicted}"
        )
        verdict = llm.generate(prompt).strip().upper()
        return verdict.startswith("YES")

    return judge


@dataclass
class CaseResult:
    question: str
    retrieved_evidence_hit: bool
    predicted_answer: str
    correct: bool


@dataclass
class ConversationResult:
    sample_id: str
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def recall_at_k(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.retrieved_evidence_hit for c in self.cases) / len(self.cases)

    @property
    def accuracy(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.correct for c in self.cases) / len(self.cases)


def run_conversation(
    conversation: Conversation,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    top_k: int = 10,
    max_qa_pairs: int | None = None,
    scorer: AnswerScorer = exact_or_substring_match,
) -> ConversationResult:
    store = LocalGraphStore(":memory:")
    ingestor = IncrementalIngestor(store, llm)

    turn_source_ids: set[str] = set()
    for turn in conversation.turns:
        # Prefixing the session date lets the extractor ground facts in time
        # (e.g. "上周" -> an actual date) instead of dropping "when" entirely,
        # which a bare "speaker: text" turn gives it no way to do.
        date_prefix = f"[{turn.session_date}] " if turn.session_date else ""
        ingestor.ingest(f"{date_prefix}{turn.speaker}: {turn.text}", source_id=turn.turn_id)
        turn_source_ids.add(turn.turn_id)

    result = ConversationResult(sample_id=conversation.sample_id)
    qa_pairs: list[QAPair] = conversation.qa_pairs[:max_qa_pairs]

    for qa in qa_pairs:
        entities = store.all_entities()
        relations = store.all_relations()
        entities_by_id = {e.id: e for e in entities}

        matches = match_query_to_triples(qa.question, relations, entities_by_id, embedder, top_k=top_k)
        seed_ids = {m.relation.subject_id for m in matches} | {m.relation.object_id for m in matches}
        scores = personalized_pagerank(entities, relations, seed_entity_ids=list(seed_ids))
        ranked_ids = [entity_id for entity_id, _ in rank_entities(scores)]
        context = build_context(relations, entities_by_id, ranked_ids, top_k=top_k)

        retrieved_source_ids = {
            p.source_id
            for m in matches
            for p in (
                entities_by_id.get(m.relation.subject_id).provenance
                if entities_by_id.get(m.relation.subject_id)
                else []
            )
        } | {
            p.source_id
            for m in matches
            for p in m.relation.provenance
        }
        evidence_hit = bool(retrieved_source_ids & set(qa.evidence_turn_ids))

        prompt = f"根据以下背景信息回答问题，只输出答案本身。\n背景：{context}\n问题：{qa.question}"
        predicted = llm.generate(prompt)
        correct = scorer(predicted, qa.answer)

        result.cases.append(
            CaseResult(
                question=qa.question,
                retrieved_evidence_hit=evidence_hit,
                predicted_answer=predicted,
                correct=correct,
            )
        )

    return result
