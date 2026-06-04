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

_provider: TracerProvider | None = None


def configure_tracing(exporter: SpanExporter | None = None) -> None:
    """Install a fresh module-level TracerProvider. Tests inject an exporter.

    We keep the provider in a module-level variable rather than OpenTelemetry's
    write-once global (`trace.set_tracer_provider` is silently ignored on the
    2nd+ call per process), so each call — and each test — gets its own provider
    and exporter without touching OTel internals.
    """
    global _provider
    provider = TracerProvider()
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    _provider = provider


def get_tracer() -> trace.Tracer:
    if _provider is None:
        # No configure_tracing() call yet → OTel's no-op proxy tracer.
        return trace.get_tracer(_TRACER_NAME)
    return _provider.get_tracer(_TRACER_NAME)
