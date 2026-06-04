from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.observability.spans import (
    SPAN_SESSION,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)


def test_configure_tracing_records_spans():
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_STEP) as step:
        step.set_attribute("step.id", "plan")
        with tracer.start_as_current_span(SPAN_SESSION) as sess:
            sess.set_attribute("session.id", "s1")

    spans = exporter.get_finished_spans()
    names = {s.name for s in spans}
    assert SPAN_STEP in names
    assert SPAN_SESSION in names
    step_span = next(s for s in spans if s.name == SPAN_STEP)
    assert step_span.attributes["step.id"] == "plan"


def test_span_name_constants_exist():
    from orchestrator.observability.spans import (
        SPAN_FILE_EDIT,
        SPAN_RUN,
        SPAN_TOOL_CALL,
    )

    assert {SPAN_RUN, SPAN_TOOL_CALL, SPAN_FILE_EDIT}
