from orchestrator.harness.events import Cost, FileEdit, MessageChunk, SessionStarted, ToolCall
from orchestrator.harness.opencode import parse_opencode_line

# Real opencode nests the payload under `part`; the event top level carries only
# type/sessionID/timestamp. These fixtures mirror the shapes captured from the
# real `opencode run --format json` binary.


def test_step_start_to_session_started():
    evs = parse_opencode_line(
        {"type": "step_start", "sessionID": "oc-1", "part": {"type": "step-start"}}, {}
    )
    assert evs == [SessionStarted("oc-1")]


def test_text_to_message_chunk():
    evs = parse_opencode_line({"type": "text", "part": {"type": "text", "text": "hello "}}, {})
    assert evs == [MessageChunk("hello ")]


def test_tool_use_read_completed_no_fileedit():
    evs = parse_opencode_line(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "read",
                "callID": "t1",
                "state": {"status": "completed", "input": {"filePath": "README.md"}},
            },
        },
        {},
    )
    assert ToolCall("read", "completed") in evs
    assert not any(isinstance(e, FileEdit) for e in evs)


def test_tool_use_edit_emits_fileedit():
    evs = parse_opencode_line(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "edit",
                "callID": "t2",
                "state": {"status": "completed", "input": {"filePath": "src/a.py"}},
            },
        },
        {},
    )
    assert ToolCall("edit", "completed") in evs
    assert FileEdit("src/a.py", "modify") in evs


def test_step_finish_emits_cost_with_token_dict():
    evs = parse_opencode_line(
        {"type": "step_finish", "part": {"cost": 0.004, "tokens": {"total": 120}}}, {}
    )
    assert evs == [Cost(usd=0.004, tokens=120)]


def test_unknown_event_ignored():
    assert parse_opencode_line({"type": "whatever"}, {}) == []
