import numpy as np

from benchmarks.harness import run_conversation
from benchmarks.loaders import Conversation, DialogueTurn, QAPair
from memory_core.llm.base import LLMProvider, TripleCandidate


class ScriptedLLMProvider(LLMProvider):
    """Extracts a fixed triple keyed by the exact ingested text, and answers
    questions by echoing the assembled context back — enough to prove the
    harness plumbing (ingest -> retrieve -> score) works without a real model."""

    def __init__(self, triples_by_text: dict[str, TripleCandidate]) -> None:
        self._triples_by_text = triples_by_text

    def extract_triples(self, text: str) -> list[TripleCandidate]:
        triple = self._triples_by_text.get(text)
        return [triple] if triple else []

    def generate(self, prompt: str, **kwargs: object) -> str:
        return prompt.split("背景：")[1].split("\n问题：")[0]


class FakeEmbeddingProvider:
    def embed(self, texts: list[str]) -> np.ndarray:
        vocab = sorted({ch for t in texts for ch in t}) or ["_"]
        return np.array([[t.count(ch) for ch in vocab] for t in texts], dtype=float)


def test_run_conversation_wires_ingest_retrieve_and_score():
    conversation = Conversation(
        sample_id="test-1",
        turns=[
            DialogueTurn(turn_id="D1:1", speaker="A", text="我在某公司工作"),
            DialogueTurn(turn_id="D1:2", speaker="A", text="今天天气不错"),
        ],
        qa_pairs=[QAPair(question="A在哪里工作？", answer="某公司", evidence_turn_ids=["D1:1"])],
    )

    llm = ScriptedLLMProvider(
        {
            "A: 我在某公司工作": TripleCandidate(
                subject="A", predicate="工作于", object="某公司", source_span="我在某公司工作"
            ),
            "A: 今天天气不错": TripleCandidate(
                subject="A", predicate="聊到", object="天气", source_span="今天天气不错"
            ),
        }
    )

    embedder = FakeEmbeddingProvider()
    result = run_conversation(conversation, llm, embedder, top_k=5)

    assert result.sample_id == "test-1"
    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.retrieved_evidence_hit  # D1:1's fact is the one that should surface
    assert "某公司" in case.predicted_answer
    assert case.correct
