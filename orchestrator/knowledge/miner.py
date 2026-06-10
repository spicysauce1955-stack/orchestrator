"""Offline knowledge miner (spec §8.1): span store → candidate lessons.

Capture → codify → propagate, *governed*: the miner scans the durable span
store (M6d) for patterns repeated across runs and renders candidate lessons.
Candidates are never written to the knowledge base here — the `auditor` role
vets them and approves through the existing deny-wins gated
`mcp__knowledge__write` path (M6b). Deterministic detectors, no LLM.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from orchestrator.observability.store import connect


@dataclass(frozen=True)
class Candidate:
    kind: str
    subject: str
    runs: tuple[str, ...]
    count: int
    text: str


def _trace_runs(conn: sqlite3.Connection) -> dict[str, str]:
    """trace_id → run_id via each root `run` span (a run may own several traces)."""
    rows = conn.execute(
        "SELECT trace_id, json_extract(attrs, '$.\"run.id\"') FROM spans WHERE name = 'run'"
    )
    return {str(t): str(r) for t, r in rows if r is not None}


def _step_failures(conn: sqlite3.Connection, traces: dict[str, str], min_runs: int):
    grouped: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT trace_id, attrs FROM spans "
        "WHERE name = 'step' AND json_extract(attrs, '$.\"step.is_error\"')"
    )
    for trace_id, raw in rows:
        run = traces.get(str(trace_id))
        if run is None:
            continue
        attrs = json.loads(raw)
        step = str(attrs.get("step.id", ""))
        g = grouped.setdefault(step, {"runs": set(), "count": 0, "role": ""})
        g["runs"].add(run)
        g["count"] += 1
        g["role"] = str(attrs.get("step.role", "")) or g["role"]
    for step, g in grouped.items():
        if len(g["runs"]) < min_runs:
            continue
        runs = tuple(sorted(g["runs"]))
        yield Candidate(
            kind="recurring_step_failure",
            subject=step,
            runs=runs,
            count=g["count"],
            text=(
                f"Step '{step}' (role {g['role']}) failed in {len(runs)} runs "
                f"({', '.join(runs)}) — {g['count']} failure(s) total. Consider a "
                "durable lesson about why this step keeps failing."
            ),
        )


def _repeated_rejections(conn: sqlite3.Connection, traces: dict[str, str], min_runs: int):
    grouped: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT trace_id, attrs, start_ns FROM spans "
        "WHERE name = 'message' AND json_extract(attrs, '$.\"msg.kind\"') = 'verdict' "
        "ORDER BY start_ns"
    )
    for trace_id, raw, _start in rows:
        run = traces.get(str(trace_id))
        if run is None:
            continue
        attrs = json.loads(raw)
        step = str(attrs.get("msg.to", ""))
        g = grouped.setdefault(step, {"runs": set(), "count": 0, "last": ""})
        g["runs"].add(run)
        g["count"] += 1
        g["last"] = str(attrs.get("msg.body", ""))  # rows are time-ordered
    for step, g in grouped.items():
        if len(g["runs"]) < min_runs:
            continue
        runs = tuple(sorted(g["runs"]))
        yield Candidate(
            kind="repeated_rejection",
            subject=step,
            runs=runs,
            count=g["count"],
            text=(
                f"Review rejected step '{step}' {g['count']} time(s) across "
                f"{len(runs)} runs ({', '.join(runs)}) — a systematic gap, not a "
                f"one-off. Latest feedback: {g['last'][:200]}"
            ),
        )


def mine(span_db: Path, *, min_runs: int = 2) -> list[Candidate]:
    """Patterns repeated in >= `min_runs` distinct runs, most-evidenced first."""
    with contextlib.closing(connect(span_db)) as conn:
        traces = _trace_runs(conn)
        cands = [
            *_step_failures(conn, traces, min_runs),
            *_repeated_rejections(conn, traces, min_runs),
        ]
    cands.sort(key=lambda c: (-c.count, c.kind, c.subject))
    return cands


def write_candidates(cands: list[Candidate], path: Path) -> None:
    raise NotImplementedError
