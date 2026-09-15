"""Epic 13.1: strip high-confidence secret formats out of text before it
ever reaches an LLM extraction call.

This protects against two distinct things, not just one: a secret pasted
into a conversation being written into permanent (if encrypted) storage,
AND that same secret being sent in plaintext to a third-party LLM API
provider in the first place -- the second risk exists even for the
stateless /demo/try endpoint, which never persists anything but still
makes a real extraction call.

Deliberately a small allowlist of well-known, high-signature formats
(same conservative-over-clever principle as
``graph.incremental``'s low-information filter) rather than a generic
"looks like a random string" heuristic, which would false-positive on
legitimate content (hashes, IDs, code).
"""

from __future__ import annotations

import re

_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_api_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "anthropic_api_key": re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "gitlab_token": re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"),
    "npm_token": re.compile(r"npm_[A-Za-z0-9]{36,}"),
    "google_api_key": re.compile(r"AIza[A-Za-z0-9\-_]{35}"),
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    "bearer_token": re.compile(r"[Bb]earer\s+[A-Za-z0-9\-_.]{20,}"),
}


def redact_secrets(text: str) -> str:
    """Replace matched secret substrings with a labeled placeholder,
    leaving the rest of the sentence untouched so the fact around the
    secret ("the API key is <X>, used in src/middleware/auth.ts") can
    still be extracted normally -- redacting only the sensitive token
    itself, not the whole message."""
    for label, pattern in _SECRET_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{label.upper()}]", text)
    return text
