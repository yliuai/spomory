"""Epic 4.3: a pure-vector-retrieval baseline to compare the HippoRAG-style
pipeline (query_match -> PPR diffusion -> ranker) against.

Uses the exact same ingestion and the exact same query_match step, but
skips PPR diffusion entirely — the retrieved context is just the top-K
triples ranked by direct query-to-triple embedding similarity, the way a
plain vector-store-backed RAG system would do it. This isolates what PPR
diffusion specifically contributes, rather than comparing against a
different system's whole pipeline (extraction quality, prompt, etc. all
stay identical between the two runs).
"""

from __future__ import annotations

from memory_core.graph.incremental import IncrementalIngestor
from memory_core.graph.local_store import LocalGraphStore
from memory_core.llm.base import LLMProvider
from memory_core.llm.embedding_base import EmbeddingProvider
from memory_core.retrieval.query_match import match_query_to_triples

from .harness import CaseResult, ConversationResult, exact_or_substring_match
from .loaders import Conversation


def _sentence(relation, entities_by_id) -> str:
    subject = entities_by_id.get(relation.subject_id)
    obj = entities_by_id.get(relation.object_id)
    subject_name = subject.name if subject else relation.subject_id
    object_name = obj.name if obj else relation.object_id
    return f"{subject_name}{relation.predicate}{object_name}。"


def run_conversation_vector_baseline(
    conversation: Conversation,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    top_k: int = 10,
    max_qa_pairs: int | None = None,
) -> ConversationResult:
    store = LocalGraphStore(":memory:")
    ingestor = IncrementalIngestor(store, llm)
    for turn in conversation.turns:
        ingestor.ingest(f"{turn.speaker}: {turn.text}", source_id=turn.turn_id)

    result = ConversationResult(sample_id=conversation.sample_id)
    for qa in conversation.qa_pairs[:max_qa_pairs]:
        entities = store.all_entities()
        relations = store.all_relations()
        entities_by_id = {e.id: e for e in entities}

        matches = match_query_to_triples(qa.question, relations, entities_by_id, embedder, top_k=top_k)
        context = "".join(_sentence(m.relation, entities_by_id) for m in matches)

        retrieved_source_ids = {p.source_id for m in matches for p in m.relation.provenance}
        evidence_hit = bool(retrieved_source_ids & set(qa.evidence_turn_ids))

        prompt = f"根据以下背景信息回答问题，只输出答案本身。\n背景：{context}\n问题：{qa.question}"
        predicted = llm.generate(prompt)
        correct = exact_or_substring_match(predicted, qa.answer)

        result.cases.append(
            CaseResult(
                question=qa.question,
                retrieved_evidence_hit=evidence_hit,
                predicted_answer=predicted,
                correct=correct,
            )
        )

    return result
