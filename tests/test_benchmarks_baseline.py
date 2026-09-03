from benchmarks.baseline import run_conversation_vector_baseline
from benchmarks.loaders import Conversation, DialogueTurn, QAPair
from tests.test_benchmarks_harness import FakeEmbeddingProvider, ScriptedLLMProvider


def test_vector_baseline_wires_ingest_retrieve_and_score():
    conversation = Conversation(
        sample_id="test-1",
        turns=[
            DialogueTurn(turn_id="D1:1", speaker="A", text="我在某公司工作"),
            DialogueTurn(turn_id="D1:2", speaker="A", text="今天天气不错"),
        ],
        qa_pairs=[QAPair(question="A在哪里工作？", answer="某公司", evidence_turn_ids=["D1:1"])],
    )

    from memory_core.llm.base import TripleCandidate

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

    result = run_conversation_vector_baseline(conversation, llm, FakeEmbeddingProvider(), top_k=5)

    assert result.sample_id == "test-1"
    assert len(result.cases) == 1
    assert result.cases[0].correct
