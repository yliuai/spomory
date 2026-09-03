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
            for turn in conv[session_key]:
                turns.append(
                    DialogueTurn(
                        turn_id=turn["dia_id"], speaker=turn["speaker"], text=turn["text"]
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
