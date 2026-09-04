"""Fetch public benchmark datasets used by Epic 3 (RL training data) and Epic 4
(evaluation harness). Not committed to git — run this once locally / in CI.

Usage: python benchmarks/download_data.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

SOURCES = {
    # snap-research/locomo: the official LoCoMo-10 release (10 long multi-session
    # conversations, ~2000 QA pairs total with evidence dialogue-id links).
    "locomo10.json": "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
    # xiaowu0162/LongMemEval (ICLR 2025): the "oracle" variant pre-filters each
    # question's haystack down to its relevant sessions (with has_answer flags),
    # good for a harness run without also processing bulk distractor sessions.
    "longmemeval_oracle.json": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json",
}


def download_all() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in SOURCES.items():
        dest = DATA_DIR / filename
        print(f"Downloading {filename} from {url} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"  -> {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    download_all()
