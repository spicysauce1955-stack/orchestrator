"""The orchestrator's message bus (spec §7): hub-and-spoke, every message a span.

Communication between the orchestrator agent and workers (and worker↔worker,
mediated through the orchestrator in the MVP) flows through `MessageBus.send`,
which emits one OTel `message` span per message and appends to an in-memory log
(the "coordination board" derived view). The bus holds no transport — workers
are driven by the scheduler; this records and traces the coordination.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.observability.spans import SPAN_MESSAGE, get_tracer


@dataclass(frozen=True)
class Message:
    frm: str
    to: str
    kind: str  # "classify" | "verdict" | "question" | "answer"
    body: str


class MessageBus:
    def __init__(self) -> None:
        self.log: list[Message] = []

    def send(self, frm: str, to: str, kind: str, body: str) -> Message:
        msg = Message(frm, to, kind, body)
        with get_tracer().start_as_current_span(SPAN_MESSAGE) as span:
            span.set_attribute("msg.from", frm)
            span.set_attribute("msg.to", to)
            span.set_attribute("msg.kind", kind)
        self.log.append(msg)
        return msg
