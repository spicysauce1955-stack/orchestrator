"""OTel GenAI-style spans for runs/steps/sessions/tools (spec §9).

MVP sink: tests inject InMemorySpanExporter; runtime uses a console/file
exporter. Span hierarchy for one agent step:
    run → step → harness.session → (tool_call | file_edit)
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter

SPAN_RUN = "run"
SPAN_STEP = "step"
SPAN_SESSION = "harness.session"
SPAN_TOOL_CALL = "tool_call"
SPAN_FILE_EDIT = "file_edit"

_TRACER_NAME = "orchestrator"


def configure_tracing(exporter: SpanExporter | None = None) -> None:
    """Install a TracerProvider. Idempotent per process for a given exporter.

    If `exporter` is None, a no-op provider is installed (spans are created but
    not exported) — callers that want output pass a concrete exporter.
    """
    provider = TracerProvider()
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)
