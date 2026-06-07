from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.agents.message_bus import Message, MessageBus
from orchestrator.observability.spans import configure_tracing


def _exporter():
    exp = InMemorySpanExporter()
    configure_tracing(exp)
    return exp


def test_send_returns_message_and_appends_to_log():
    bus = MessageBus()
    msg = bus.send("orchestrator", "implement", "verdict", "reject: fix the bug")
    assert msg == Message("orchestrator", "implement", "verdict", "reject: fix the bug")
    assert bus.log == [msg]


def test_send_emits_one_message_span_with_attributes():
    exp = _exporter()
    bus = MessageBus()
    bus.send("implement", "orchestrator", "question", "which db?")
    spans = [s for s in exp.get_finished_spans() if s.name == "message"]
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert attrs["msg.from"] == "implement"
    assert attrs["msg.to"] == "orchestrator"
    assert attrs["msg.kind"] == "question"
    assert attrs["msg.body"] == "which db?"


def test_log_preserves_order():
    bus = MessageBus()
    bus.send("orchestrator", "run", "classify", "feature")
    bus.send("implement", "orchestrator", "question", "q")
    bus.send("orchestrator", "implement", "answer", "a")
    assert [m.kind for m in bus.log] == ["classify", "question", "answer"]
