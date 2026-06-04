from orchestrator.harness.claude_code import parse_line
from orchestrator.harness.events import (
    Cost,
    Done,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)


def test_parse_system_init():
    state: dict[str, str] = {}
    events = parse_line(
        {"type": "system", "subtype": "init", "session_id": "s1"}, state
    )
    assert events == [SessionStarted("s1")]


def test_parse_assistant_text():
    state: dict[str, str] = {}
    events = parse_line(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        state,
    )
    assert events == [MessageChunk("hi")]


def test_parse_tool_use_emits_in_progress_and_records_name():
    state: dict[str, str] = {}
    events = parse_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}
                ]
            },
        },
        state,
    )
    assert events == [ToolCall("Read", "in_progress")]
    assert state["t1"] == "Read"


def test_parse_tool_use_write_also_emits_file_edit():
    state: dict[str, str] = {}
    events = parse_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "w1",
                        "name": "Write",
                        "input": {"file_path": "src/a.py"},
                    }
                ]
            },
        },
        state,
    )
    assert ToolCall("Write", "in_progress") in events
    assert FileEdit("src/a.py", "create") in events


def test_parse_tool_result_completes_known_call():
    state = {"t1": "Read"}
    events = parse_line(
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]
            },
        },
        state,
    )
    assert events == [ToolCall("Read", "completed")]


def test_parse_result_emits_cost_then_done():
    state: dict[str, str] = {}
    events = parse_line(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "done",
            "total_cost_usd": 0.03,
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
        state,
    )
    assert events == [
        Cost(usd=0.03, tokens=30),
        Done(result="done", is_error=False),
    ]


def test_parse_unknown_type_is_ignored():
    assert parse_line({"type": "stream_event", "x": 1}, {}) == []
