"""Tests for session_import.py's three parsers and the import flow.

Fixture content below is synthetic (not real user conversation data), but
shaped exactly like real Claude Code / Codex / Cursor session files --
confirmed against real local session files on a real machine before
writing these parsers (see session_import.py's module docstring).
"""

import json

from memory_core.session_import import (
    SessionImportSummary,
    import_local_sessions,
    parse_claude_code_session,
    parse_codex_session,
    parse_cursor_session,
)


def _write_jsonl(path, lines):
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def test_parse_claude_code_session_extracts_only_real_turns(tmp_path):
    path = tmp_path / "session.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "queue-operation", "operation": "enqueue", "timestamp": "t"},
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "记住我喜欢用 TypeScript"}]},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "x", "name": "Bash", "input": {}},
                        {"type": "text", "text": "好的，记住了。"},
                    ],
                },
            },
        ],
    )

    turns = parse_claude_code_session(path)

    assert turns == [("user", "记住我喜欢用 TypeScript"), ("assistant", "好的，记住了。")]


def test_parse_codex_session_excludes_developer_role(tmp_path):
    path = tmp_path / "rollout.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "session_meta", "payload": {"session_id": "x"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "<app-context>system stuff</app-context>"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "I work at Acme Corp"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Got it, noted."}],
                },
            },
        ],
    )

    turns = parse_codex_session(path)

    assert turns == [("user", "I work at Acme Corp"), ("assistant", "Got it, noted.")]


def test_parse_cursor_session_skips_lines_with_no_role(tmp_path):
    path = tmp_path / "transcript.jsonl"
    _write_jsonl(
        path,
        [
            {"role": "user", "message": {"content": [{"type": "text", "text": "Using Spomory, who is my manager?"}]}},
            {"type": "turn_ended", "status": "error", "error": "usage limit"},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Let me check."}]}},
        ],
    )

    turns = parse_cursor_session(path)

    assert turns == [("user", "Using Spomory, who is my manager?"), ("assistant", "Let me check.")]


def test_import_local_sessions_ingests_each_session_and_respects_limit(tmp_path):
    from memory_core.graph.incremental import IncrementalIngestor
    from memory_core.graph.local_store import LocalGraphStore
    from memory_core.llm.base import TripleCandidate
    from memory_core.memory_manager.policy import RuleBasedPolicy
    from tests.test_incremental import FakeLLMProvider

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    for i in range(3):
        _write_jsonl(
            sessions_dir / f"rollout-{i}.jsonl",
            [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"fact number {i}"}],
                    },
                }
            ],
        )

    store = LocalGraphStore(tmp_path / "g.sqlite3")
    llm = FakeLLMProvider([TripleCandidate(subject="a", predicate="r", object="b", source_span="s")])
    ingestor = IncrementalIngestor(store, llm, policy=RuleBasedPolicy())

    summary = import_local_sessions("codex", ingestor, limit=2, root=sessions_dir)

    assert isinstance(summary, SessionImportSummary)
    assert summary.sessions_imported == 2  # limit respected, not all 3
    # FakeLLMProvider returns the identical (a, r, b) triple regardless of
    # input text, so the second session's "new" fact resolves to the same
    # entities/relation the first one already created -- 2 new entities on
    # the first session, both merged (not duplicated) on the second.
    assert summary.total_new_entities == 2
    assert summary.total_merged_entities == 2
    # provenance records which client the fact came from, for the same
    # cross-client conflict detection add_memory's client_name feeds
    assert store.all_relations()[0].provenance[0].client_name == "codex"


def test_import_local_sessions_returns_empty_summary_for_missing_directory(tmp_path):
    from memory_core.graph.incremental import IncrementalIngestor
    from memory_core.graph.local_store import LocalGraphStore
    from memory_core.memory_manager.policy import RuleBasedPolicy
    from tests.test_incremental import FakeLLMProvider

    store = LocalGraphStore(tmp_path / "g.sqlite3")
    ingestor = IncrementalIngestor(store, FakeLLMProvider([]), policy=RuleBasedPolicy())

    summary = import_local_sessions("codex", ingestor, root=tmp_path / "does-not-exist")

    assert summary.sessions_imported == 0
    assert summary.sessions_skipped == 0


def test_unknown_client_raises():
    import pytest

    from memory_core.session_import import import_local_sessions

    with pytest.raises(ValueError, match="unknown client"):
        import_local_sessions("not-a-real-client", ingestor=None)  # type: ignore[arg-type]
