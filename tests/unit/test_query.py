from __future__ import annotations

import sqlite3
from pathlib import Path

from orchestrator.observability.query import run_status
from orchestrator.observability.spans import (
    SPAN_RUN,
    SPAN_SESSION,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)
from orchestrator.observability.store import SqliteSpanExporter, connect


def _seed(db: Path) -> None:
    """Emit a run 'r1' of pipeline 'demo': plan (ok) → implement (error)."""
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r1")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as plan:
            plan.set_attribute("step.id", "plan")
            plan.set_attribute("step.role", "planner")
            plan.set_attribute("step.is_error", False)
        with tracer.start_as_current_span(SPAN_STEP) as impl:
            impl.set_attribute("step.id", "implement")
            impl.set_attribute("step.role", "implementer")
            impl.set_attribute("step.is_error", True)
            with tracer.start_as_current_span(SPAN_SESSION) as sess:
                sess.set_attribute("cost.usd", 0.5)
                sess.set_attribute("cost.tokens", 1000)


def test_run_status_lists_steps_and_overall_state(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)

    view = run_status(db, "r1")

    assert view is not None
    assert view.pipeline == "demo"
    assert view.status == "error"  # implement failed
    assert [(s.step_id, s.role, s.is_error) for s in view.steps] == [
        ("plan", "planner", False),
        ("implement", "implementer", True),
    ]
    assert all(s.kind == "agent" for s in view.steps)  # default kind when step.type absent


def test_run_status_unknown_run_returns_none(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    assert run_status(db, "nope") is None


def test_all_spans_of_a_run_share_one_trace(tmp_path: Path) -> None:
    # Locks the invariant the queries depend on (linear MVP pipelines).
    db = tmp_path / "spans.sqlite"
    _seed(db)
    conn = connect(db)
    conn.row_factory = sqlite3.Row
    traces = {r["trace_id"] for r in conn.execute("SELECT trace_id FROM spans")}
    assert len(traces) == 1
