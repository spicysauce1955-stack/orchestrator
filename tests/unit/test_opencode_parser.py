from orchestrator.harness.events import Cost, FileEdit, MessageChunk, SessionStarted, ToolCall
from orchestrator.harness.opencode import parse_opencode_line


def test_step_start_to_session_started():
    evs = parse_opencode_line({"type": "step_start", "sessionID": "oc-1"}, {})
    assert evs == [SessionStarted("oc-1")]


def test_text_to_message_chunk():
    evs = parse_opencode_line({"type": "text", "text": "hello "}, {})
    assert evs == [MessageChunk("hello ")]


def test_tool_use_read_is_in_progress_no_fileedit():
    evs = parse_opencode_line(
        {"type": "tool_use", "tool": "read", "id": "t1", "input": {"path": "README.md"}}, {}
    )
    assert ToolCall("read", "in_progress") in evs
    assert not any(isinstance(e, FileEdit) for e in evs)


def test_tool_use_edit_emits_fileedit():
    evs = parse_opencode_line(
        {"type": "tool_use", "tool": "edit", "id": "t2", "input": {"path": "src/a.py"}}, {}
    )
    assert ToolCall("edit", "in_progress") in evs
    assert FileEdit("src/a.py", "modify") in evs


def test_step_finish_emits_cost():
    evs = parse_opencode_line({"type": "step_finish", "cost": 0.004, "tokens": 120}, {})
    assert evs == [Cost(usd=0.004, tokens=120)]


def test_unknown_event_ignored():
    assert parse_opencode_line({"type": "whatever"}, {}) == []
