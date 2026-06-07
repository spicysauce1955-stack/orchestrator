"""Read models over the span store (spec §9): status / metrics / memory lenses.

A run's spans share one trace_id; we resolve run_id → trace_id via the root
`run` span's `run.id` attribute, then read that trace.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from orchestrator.observability.store import connect


@dataclass
class StepView:
    step_id: str
    role: str
    kind: str  # "agent" | "task" | "merge"
    is_error: bool


@dataclass
class StatusView:
    run_id: str
    pipeline: str
    status: str  # "completed" | "error"
    steps: list[StepView]


def _open(db: Path) -> sqlite3.Connection:
    conn = connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _trace_for_run(conn: sqlite3.Connection, run_id: str) -> str | None:
    for row in conn.execute("SELECT trace_id, attrs FROM spans WHERE name = 'run'"):
        if json.loads(row["attrs"]).get("run.id") == run_id:
            return str(row["trace_id"])
    return None


def _spans(conn: sqlite3.Connection, trace_id: str, name: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? AND name = ? ORDER BY start_ns",
            (trace_id, name),
        )
    )


def run_status(db: Path, run_id: str) -> StatusView | None:
    with contextlib.closing(_open(db)) as conn:
        trace = _trace_for_run(conn, run_id)
        if trace is None:
            return None
        run_row = _spans(conn, trace, "run")[0]
        pipeline = json.loads(run_row["attrs"]).get("pipeline", "")
        steps: list[StepView] = []
        any_error = False
        for row in _spans(conn, trace, "step"):
            attrs = json.loads(row["attrs"])
            is_error = bool(attrs.get("step.is_error", False))
            any_error = any_error or is_error
            steps.append(
                StepView(
                    step_id=str(attrs.get("step.id", "")),
                    role=str(attrs.get("step.role", "")),
                    kind=str(attrs.get("step.type", "agent")),
                    is_error=is_error,
                )
            )
    return StatusView(
        run_id=run_id,
        pipeline=pipeline,
        status="error" if any_error else "completed",
        steps=steps,
    )


@dataclass
class StepMetric:
    step_id: str
    cost_usd: float
    tokens: int
    duration_ms: float


@dataclass
class MetricsView:
    run_id: str
    steps: list[StepMetric]
    total_cost_usd: float
    total_tokens: int


def run_metrics(db: Path, run_id: str) -> MetricsView | None:
    with contextlib.closing(_open(db)) as conn:
        trace = _trace_for_run(conn, run_id)
        if trace is None:
            return None
        # session spans carry cost; group them under their parent step span.
        cost_by_parent: dict[str, tuple[float, int]] = {}
        for row in _spans(conn, trace, "harness.session"):
            attrs = json.loads(row["attrs"])
            usd, tok = cost_by_parent.get(row["parent_id"], (0.0, 0))
            cost_by_parent[row["parent_id"]] = (
                usd + float(attrs.get("cost.usd", 0.0)),
                tok + int(attrs.get("cost.tokens", 0)),
            )
        steps: list[StepMetric] = []
        total_usd = 0.0
        total_tok = 0
        for row in _spans(conn, trace, "step"):
            attrs = json.loads(row["attrs"])
            usd, tok = cost_by_parent.get(row["span_id"], (0.0, 0))
            total_usd += usd
            total_tok += tok
            steps.append(
                StepMetric(
                    step_id=str(attrs.get("step.id", "")),
                    cost_usd=usd,
                    tokens=tok,
                    duration_ms=(int(row["end_ns"]) - int(row["start_ns"])) / 1e6,
                )
            )
    return MetricsView(
        run_id=run_id, steps=steps, total_cost_usd=total_usd, total_tokens=total_tok
    )
