"""Tests for parse_codex_line: NDJSON parser for `codex exec --json`."""

from orchestrator.harness.codex import parse_codex_line
from orchestrator.harness.events import Cost, FileEdit, MessageChunk, SessionStarted, ToolCall


def test_thread_started_to_session_started():
    evs = parse_codex_line(
        {"type": "thread.started", "thread_id": "019eacb0-b090-7d12"}, {}
    )
    assert evs == [SessionStarted("019eacb0-b090-7d12")]


def test_agent_message_completed_to_message_chunk():
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": "Inspecting the repo."},
        },
        {},
    )
    assert evs == [MessageChunk("Inspecting the repo.")]


def test_command_execution_started_and_completed_to_toolcall():
    items: dict[str, str] = {}
    started = parse_codex_line(
        {
            "type": "item.started",
            "item": {
                "id": "item_2",
                "type": "command_execution",
                "command": "/bin/bash -lc 'sed -n 1,220p x.py'",
                "status": "in_progress",
            },
        },
        items,
    )
    assert started == [ToolCall("command", "in_progress")]
    completed = parse_codex_line(
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "command_execution", "status": "completed"},
        },
        items,
    )
    assert completed == [ToolCall("command", "completed")]
    assert items["item_2"] == "command_execution"


def test_file_change_completed_emits_fileedit_per_change():
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {
                "id": "item_8",
                "type": "file_change",
                "changes": [
                    {"path": "/repo/convex_hull.py", "kind": "update"},
                    {"path": "/repo/new_module.py", "kind": "add"},
                    {"path": "/repo/old.py", "kind": "delete"},
                ],
                "status": "completed",
            },
        },
        {},
    )
    assert FileEdit("/repo/convex_hull.py", "modify") in evs
    assert FileEdit("/repo/new_module.py", "create") in evs
    assert FileEdit("/repo/old.py", "delete") in evs


def test_file_change_started_emits_nothing():
    # codex repeats the changes payload on item.started; only completion counts,
    # so a change is not double-emitted.
    evs = parse_codex_line(
        {
            "type": "item.started",
            "item": {
                "id": "item_8",
                "type": "file_change",
                "changes": [{"path": "/repo/a.py", "kind": "update"}],
                "status": "in_progress",
            },
        },
        {},
    )
    assert not any(isinstance(e, FileEdit) for e in evs)


def test_turn_completed_sums_tokens_into_cost():
    evs = parse_codex_line(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 144154,
                "cached_input_tokens": 78080,
                "output_tokens": 1487,
                "reasoning_output_tokens": 36,
            },
        },
        {},
    )
    assert evs == [Cost(usd=0.0, tokens=144154 + 1487)]


def test_error_item_emits_no_events():
    # codex emits non-fatal error items (e.g. config deprecation warnings) in
    # every run; the adapter (not the parser) decides whether to surface them.
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "error",
                "message": "`[features].codex_hooks` is deprecated.",
            },
        },
        {},
    )
    assert evs == []


def test_unknown_types_ignored():
    assert parse_codex_line({"type": "turn.started"}, {}) == []
    assert (
        parse_codex_line(
            {
                "type": "item.started",
                "item": {"id": "x", "type": "agent_message", "text": "partial"},
            },
            {},
        )
        == []
    )
    assert parse_codex_line({}, {}) == []


def test_unknown_file_change_kind_falls_back_to_modify():
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {
                "id": "item_9",
                "type": "file_change",
                "changes": [{"path": "/repo/r.py", "kind": "rename"}],
                "status": "completed",
            },
        },
        {},
    )
    assert evs == [FileEdit("/repo/r.py", "modify")]
