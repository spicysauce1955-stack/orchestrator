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

from orchestrator.observability.spans import SPAN_SESSION
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


def _traces_for_run(conn: sqlite3.Connection, run_id: str) -> list[str]:
    """All trace_ids whose root `run` span carries this run.id, in start order.

    A run has one trace; a resume opens a second `run` span (its own trace) with
    the same run.id, so a run can span multiple traces. `json_extract` pushes the
    attr filter into SQLite (no Python-side full scan).
    """
    rows = conn.execute(
        "SELECT trace_id FROM spans "
        "WHERE name = 'run' AND json_extract(attrs, '$.\"run.id\"') = ? "
        "ORDER BY start_ns",
        (run_id,),
    )
    return [str(r["trace_id"]) for r in rows]


def _spans(conn: sqlite3.Connection, traces: list[str], name: str) -> list[sqlite3.Row]:
    if not traces:
        return []
    placeholders = ",".join("?" * len(traces))
    return list(
        conn.execute(
            f"SELECT * FROM spans WHERE trace_id IN ({placeholders}) AND name = ? "
            "ORDER BY start_ns",
            (*traces, name),
        )
    )


def run_status(db: Path, run_id: str) -> StatusView | None:
    with contextlib.closing(_open(db)) as conn:
        traces = _traces_for_run(conn, run_id)
        if not traces:
            return None
        run_rows = _spans(conn, traces, "run")
        pipeline = json.loads(run_rows[0]["attrs"]).get("pipeline", "")
        # Terminal status from the last run span that recorded one (resume wins).
        explicit_status: str | None = None
        for row in run_rows:
            recorded = json.loads(row["attrs"]).get("run.status")
            if recorded:
                explicit_status = str(recorded)
        # Dedup steps by id across traces (a resumed step re-executes), latest wins.
        steps: dict[str, StepView] = {}
        for row in _spans(conn, traces, "step"):
            attrs = json.loads(row["attrs"])
            sid = str(attrs.get("step.id", ""))
            steps[sid] = StepView(
                step_id=sid,
                role=str(attrs.get("step.role", "")),
                kind=str(attrs.get("step.type", "agent")),
                is_error=bool(attrs.get("step.is_error", False)),
            )
    any_error = any(s.is_error for s in steps.values())
    return StatusView(
        run_id=run_id,
        pipeline=pipeline,
        status=explicit_status or ("error" if any_error else "completed"),
        steps=list(steps.values()),
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
        traces = _traces_for_run(conn, run_id)
        if not traces:
            return None
        # session spans carry cost; group them under their parent step span.
        cost_by_parent: dict[str, tuple[float, int]] = {}
        for row in _spans(conn, traces, SPAN_SESSION):
            attrs = json.loads(row["attrs"])
            usd, tok = cost_by_parent.get(row["parent_id"], (0.0, 0))
            cost_by_parent[row["parent_id"]] = (
                usd + float(attrs.get("cost.usd", 0.0)),
                tok + int(attrs.get("cost.tokens", 0)),
            )
        steps: list[StepMetric] = []
        total_usd = 0.0
        total_tok = 0
        for row in _spans(conn, traces, "step"):
            attrs = json.loads(row["attrs"])
            usd, tok = cost_by_parent.get(row["span_id"], (0.0, 0))
            total_usd += usd
            total_tok += tok
            steps.append(
                StepMetric(
                    step_id=str(attrs.get("step.id", "")),
                    cost_usd=usd,
                    tokens=tok,
                    duration_ms=max(0.0, (int(row["end_ns"]) - int(row["start_ns"])) / 1e6),
                )
            )
    return MetricsView(
        run_id=run_id, steps=steps, total_cost_usd=total_usd, total_tokens=total_tok
    )


@dataclass
class MessageView:
    frm: str
    to: str
    kind: str
    body: str


def run_messages(db: Path, run_id: str) -> list[MessageView]:
    """The coordination board for a run: `message` spans in time order.

    Forward-compatible: when `knowledge.write` span emission lands (deferred,
    cross-process), add its name here — no caller change needed.
    """
    with contextlib.closing(_open(db)) as conn:
        traces = _traces_for_run(conn, run_id)
        if not traces:
            return []
        out: list[MessageView] = []
        for row in _spans(conn, traces, "message"):
            attrs = json.loads(row["attrs"])
            out.append(
                MessageView(
                    frm=str(attrs.get("msg.from", "")),
                    to=str(attrs.get("msg.to", "")),
                    kind=str(attrs.get("msg.kind", "")),
                    body=str(attrs.get("msg.body", "")),
                )
            )
    return out
