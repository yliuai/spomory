"""Parse the public LoCoMo / LongMemEval benchmark files into a common,
memory-core-friendly shape: one memory-worthy text per dialogue turn, and a
list of (question, answer, evidence turn ids) QA pairs per conversation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@dataclass
class DialogueTurn:
    turn_id: str  # e.g. "D1:3"
    speaker: str
    text: str
    session_date: str = ""  # e.g. "1:56 pm on 8 May, 2023" — the session this turn is in


@dataclass
class QAPair:
    question: str
    answer: str
    evidence_turn_ids: list[str]
    category: int | None = None


@dataclass
class Conversation:
    sample_id: str
    turns: list[DialogueTurn]
    qa_pairs: list[QAPair]


def load_longmemeval(path: Path | None = None, limit: int | None = None) -> list[Conversation]:
    """Load LongMemEval's "oracle" variant (github.com/xiaowu0162/LongMemEval,
    ICLR 2025): each question comes with its own pre-filtered set of relevant
    sessions rather than sharing one long conversation the way LoCoMo does, so
    each question is modeled as its own single-QA-pair ``Conversation``.
    """
    path = path or DATA_DIR / "longmemeval_oracle.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `python benchmarks/download_data.py` first"
        )

    raw = json.loads(path.read_text())[:limit]
    conversations: list[Conversation] = []
    for sample in raw:
        turns: list[DialogueTurn] = []
        evidence_turn_ids: list[str] = []
        for session_idx, session in enumerate(sample["haystack_sessions"]):
            session_date = sample["haystack_dates"][session_idx]
            session_id = sample["haystack_session_ids"][session_idx]
            for turn_idx, turn in enumerate(session):
                turn_id = f"{session_id}:{turn_idx}"
                turns.append(
                    DialogueTurn(
                        turn_id=turn_id,
                        speaker=turn["role"],
                        text=turn["content"],
                        session_date=session_date,
                    )
                )
                if turn.get("has_answer"):
                    evidence_turn_ids.append(turn_id)

        qa_pairs = [
            QAPair(
                question=sample["question"],
                answer=sample["answer"],
                evidence_turn_ids=evidence_turn_ids,
                category=None,
            )
        ]
        conversations.append(
            Conversation(sample_id=sample["question_id"], turns=turns, qa_pairs=qa_pairs)
        )

    return conversations


def load_locomo(path: Path | None = None) -> list[Conversation]:
    """Load the LoCoMo-10 dataset (download it first via ``download_data.py``)."""
    path = path or DATA_DIR / "locomo10.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `python benchmarks/download_data.py` first"
        )

    raw = json.loads(path.read_text())
    conversations: list[Conversation] = []
    for sample in raw:
        turns: list[DialogueTurn] = []
        conv = sample["conversation"]
        session_keys = sorted(
            (k for k in conv if k.startswith("session_") and not k.endswith("_date_time")),
            key=lambda k: int(k.split("_")[1]),
        )
        for session_key in session_keys:
            session_date = conv.get(f"{session_key}_date_time", "")
            for turn in conv[session_key]:
                turns.append(
                    DialogueTurn(
                        turn_id=turn["dia_id"],
                        speaker=turn["speaker"],
                        text=turn["text"],
                        session_date=session_date,
                    )
                )

        qa_pairs = [
            QAPair(
                question=qa["question"],
                # Category 5 = adversarial (unanswerable) questions: LoCoMo
                # gives an "adversarial_answer" trap instead of a real "answer".
                answer=str(qa.get("answer", qa.get("adversarial_answer", ""))),
                evidence_turn_ids=qa.get("evidence", []),
                category=qa.get("category"),
            )
            for qa in sample["qa"]
        ]

        conversations.append(
            Conversation(sample_id=sample["sample_id"], turns=turns, qa_pairs=qa_pairs)
        )

    return conversations
