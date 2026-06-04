from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)


def test_event_types_are_frozen_dataclasses():
    s = SessionStarted(session_id="sess-1")
    assert s.session_id == "sess-1"
    import dataclasses

    assert dataclasses.is_dataclass(s)
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        s.session_id = "other"  # type: ignore[misc]


def test_event_fields():
    assert MessageChunk(text="hi").text == "hi"
    tc = ToolCall(name="Read", status="completed")
    assert (tc.name, tc.status) == ("Read", "completed")
    fe = FileEdit(path="src/a.py", kind="modify")
    assert (fe.path, fe.kind) == ("src/a.py", "modify")
    c = Cost(usd=0.01, tokens=150)
    assert (c.usd, c.tokens) == (0.01, 150)
    d = Done(result="ok", is_error=False)
    assert (d.result, d.is_error) == ("ok", False)


def test_event_union_membership():
    events: list[Event] = [
        SessionStarted("s"),
        MessageChunk("t"),
        ToolCall("Read", "completed"),
        FileEdit("a", "create"),
        Cost(0.0, 0),
        Done("", False),
    ]
    assert len(events) == 6
