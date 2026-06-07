from __future__ import annotations

import sqlite3
from pathlib import Path

from orchestrator.observability.query import run_messages, run_metrics, run_status
from orchestrator.observability.spans import (
    SPAN_MESSAGE,
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


def test_run_metrics_rolls_up_cost_per_step_and_total(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)  # implement step has one session: $0.5 / 1000 tokens

    view = run_metrics(db, "r1")

    assert view is not None
    by_step = {m.step_id: m for m in view.steps}
    assert by_step["implement"].cost_usd == 0.5
    assert by_step["implement"].tokens == 1000
    assert by_step["plan"].cost_usd == 0.0  # no session under plan
    assert view.total_cost_usd == 0.5
    assert view.total_tokens == 1000
    assert by_step["implement"].duration_ms >= 0.0


def test_run_messages_returns_message_spans_in_order(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r2")
        run.set_attribute("pipeline", "qa-demo")
        for frm, to, kind, body in [
            ("orchestrator", "implement", "classify", "feature"),
            ("implement", "orchestrator", "question", "which db?"),
            ("orchestrator", "implement", "answer", "sqlite"),
        ]:
            with tracer.start_as_current_span(SPAN_MESSAGE) as m:
                m.set_attribute("msg.from", frm)
                m.set_attribute("msg.to", to)
                m.set_attribute("msg.kind", kind)
                m.set_attribute("msg.body", body)

    msgs = run_messages(db, "r2")

    assert [(m.frm, m.to, m.kind, m.body) for m in msgs] == [
        ("orchestrator", "implement", "classify", "feature"),
        ("implement", "orchestrator", "question", "which db?"),
        ("orchestrator", "implement", "answer", "sqlite"),
    ]


def test_run_metrics_unknown_run_returns_none(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    assert run_metrics(db, "nope") is None


def test_run_messages_unknown_run_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    assert run_messages(db, "nope") == []
