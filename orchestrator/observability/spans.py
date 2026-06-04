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
    """Install a TracerProvider. Always replaces the current provider.

    If `exporter` is None, a no-op provider is installed (spans are created but
    not exported) — callers that want output pass a concrete exporter.

    Uses OTel's internal _set_tracer_provider with log=False to suppress the
    "Overriding not allowed" warning; this is intentional for test isolation
    where each test installs its own InMemorySpanExporter.
    """
    provider = TracerProvider()
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Force-reset the once-guard so the provider can be replaced (test isolation).
    # This is necessary because OTel's set_tracer_provider only allows one call
    # per process; tests need to swap exporters between test runs.
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._set_tracer_provider(provider, log=False)  # type: ignore[attr-defined]


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)
