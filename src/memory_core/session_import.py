"""Phase 0 item: import existing local coding-agent session transcripts
(Claude Code, Codex, Cursor) into the memory graph, instead of a brand-new
account starting completely empty.

Reuses `IncrementalIngestor` -- the same extraction pipeline `add_memory`
calls -- rather than building a separate verbatim-transcript archive/search
system (that's a much bigger, explicitly-deferred piece of work; see
TASKS.md). Each session's real user/assistant text turns get assembled
into one block of text per session and run through the normal fact
extraction, same as if you'd pasted that conversation into `add_memory`
by hand.

Each client stores its own sessions in its own JSONL shape, discovered by
reading real session files on a real machine for this project (not
guessed from a spec): see `_PARSERS` below.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from memory_core.graph.incremental import IncrementalIngestor

_SessionTurn = tuple[str, str]  # (role, text)


def _text_blocks(content: object) -> Iterator[str]:
    """`content` is the list-of-blocks shape all three clients use for a
    single message -- yields the text of every block whose type marks it
    as plain text, skipping tool calls/results and anything else that
    isn't actual conversation."""
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text"):
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                yield text


def parse_claude_code_session(path: Path) -> list[_SessionTurn]:
    """Claude Code's transcript: one JSON object per line, most of them
    `type: "queue-operation"`/other bookkeeping -- only `type: "user"` and
    `type: "assistant"` lines are real conversation turns, each with a
    `message.content` block list."""
    turns: list[_SessionTurn] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role", entry["type"])
        text = "\n".join(_text_blocks(message.get("content")))
        if text.strip():
            turns.append((role, text))
    return turns


def parse_codex_session(path: Path) -> list[_SessionTurn]:
    """Codex's transcript: one JSON object per line, conversation turns are
    `type: "response_item"` with `payload.type == "message"`. `payload.role`
    is "user", "assistant", or "developer" -- "developer" is the injected
    app-context/system prompt, not something the user or Codex actually
    said, so it's excluded."""
    turns: list[_SessionTurn] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in ("user", "assistant"):
            continue
        text = "\n".join(_text_blocks(payload.get("content")))
        if text.strip():
            turns.append((role, text))
    return turns


def parse_cursor_session(path: Path) -> list[_SessionTurn]:
    """Cursor's agent-transcripts: one JSON object per line, shaped
    `{"role": "user"|"assistant", "message": {"content": [...]}}`. Some
    lines (e.g. `{"type": "turn_ended", ...}`) have no `role` at all and
    aren't conversation turns."""
    turns: list[_SessionTurn] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        text = "\n".join(_text_blocks(message.get("content")))
        if text.strip():
            turns.append((role, text))
    return turns


@dataclass
class _ClientSpec:
    default_dir: Path
    glob: str
    parser: object


_PARSERS: dict[str, _ClientSpec] = {
    "claude-code": _ClientSpec(Path.home() / ".claude" / "projects", "**/*.jsonl", parse_claude_code_session),
    "codex": _ClientSpec(Path.home() / ".codex" / "sessions", "**/*.jsonl", parse_codex_session),
    "cursor": _ClientSpec(Path.home() / ".cursor" / "projects", "**/agent-transcripts/**/*.jsonl", parse_cursor_session),
}


def _render_transcript(turns: list[_SessionTurn]) -> str:
    return "\n\n".join(f"{role.capitalize()}: {text}" for role, text in turns)


@dataclass
class SessionImportSummary:
    sessions_imported: int = 0
    sessions_skipped: int = 0
    total_new_entities: int = 0
    total_merged_entities: int = 0
    total_new_relations: int = 0
    errors: list[str] = field(default_factory=list)


def import_local_sessions(
    client: str, ingestor: IncrementalIngestor, limit: int | None = None, root: Path | None = None
) -> SessionImportSummary:
    """Find `client`'s local session files, extract the real conversation
    turns from each, and ingest each session as one `add_memory`-equivalent
    call (`source_id` is the session file's path, so provenance points back
    to exactly which session a fact came from).

    `limit`: import at most this many sessions, most-recently-modified
    first -- real session directories can hold hundreds of files, and each
    one costs a real extraction LLM call, so this is opt-in protection
    against an accidental huge/expensive first run, not a correctness
    requirement.
    """
    if client not in _PARSERS:
        raise ValueError(f"unknown client {client!r}, expected one of {sorted(_PARSERS)}")
    spec = _PARSERS[client]
    search_root = root if root is not None else spec.default_dir

    summary = SessionImportSummary()
    if not search_root.exists():
        return summary

    files = sorted(search_root.glob(spec.glob), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        files = files[:limit]

    for path in files:
        try:
            turns = spec.parser(path)
        except (OSError, UnicodeDecodeError) as exc:
            summary.sessions_skipped += 1
            summary.errors.append(f"{path}: {exc}")
            continue

        text = _render_transcript(turns)
        if not text.strip():
            summary.sessions_skipped += 1
            continue

        result = ingestor.ingest(text, source_id=str(path), client_name=client)
        summary.sessions_imported += 1
        summary.total_new_entities += result.new_entities
        summary.total_merged_entities += result.merged_entities
        summary.total_new_relations += result.new_relations

    return summary


def main() -> None:
    """CLI entry point (`spomory-import-sessions`): reuses the same
    env-configured LLM/embedder/store `memory-core-mcp` itself uses, so
    importing is a drop-in extra step with no separate configuration."""
    import argparse

    from memory_core.llm.openai_compatible import OpenAICompatibleProvider
    from memory_core.mcp_server.server import _select_store_from_env
    from memory_core.memory_manager.policy import RuleBasedPolicy

    parser = argparse.ArgumentParser(
        description="Import existing local Claude Code / Codex / Cursor session transcripts into Spomory's memory graph."
    )
    parser.add_argument("--client", required=True, choices=sorted(_PARSERS), help="which client's sessions to import")
    parser.add_argument(
        "--limit", type=int, default=20, help="import at most this many sessions, most recent first (default: 20)"
    )
    args = parser.parse_args()

    store = _select_store_from_env()
    llm = OpenAICompatibleProvider()
    ingestor = IncrementalIngestor(store, llm, policy=RuleBasedPolicy())

    summary = import_local_sessions(args.client, ingestor, limit=args.limit)
    print(
        f"Imported {summary.sessions_imported} session(s), skipped {summary.sessions_skipped} "
        f"(empty or unreadable). New entities: {summary.total_new_entities} "
        f"(merged {summary.total_merged_entities}), new relations: {summary.total_new_relations}."
    )
    for err in summary.errors:
        print(f"  error: {err}")


if __name__ == "__main__":
    main()
