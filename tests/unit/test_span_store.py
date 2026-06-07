from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from orchestrator.observability.spans import (
    SPAN_RUN,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)
from orchestrator.observability.store import SqliteSpanExporter, connect


def _emit(db: Path) -> None:
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "abc123")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as step:
            step.set_attribute("step.id", "plan")


def test_exporter_writes_one_row_per_span_sharing_a_trace(tmp_path: Path) -> None:
    db = tmp_path / ".orch" / "spans.sqlite"
    _emit(db)

    conn = connect(db)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT * FROM spans ORDER BY name"))

    assert {r["name"] for r in rows} == {SPAN_RUN, SPAN_STEP}
    assert len({r["trace_id"] for r in rows}) == 1
    run_row = next(r for r in rows if r["name"] == SPAN_RUN)
    step_row = next(r for r in rows if r["name"] == SPAN_STEP)
    assert step_row["parent_id"] == run_row["span_id"]
    assert run_row["parent_id"] is None
    assert json.loads(run_row["attrs"])["run.id"] == "abc123"
    assert run_row["end_ns"] >= run_row["start_ns"] > 0
