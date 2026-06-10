"""GC for the durable .orch/ stores (M5/M6d follow-up: they grew unbounded).

Drops whole old *runs*: every span trace whose root `run` span carries a
dropped run.id, and the matching checkpoint thread (thread_id == run_id) in
the LangGraph checkpoint DB. A run's age is the start of its newest `run`
span (a resume refreshes it). Checkpoint threads with no span record have an
unknowable age and are left untouched.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.observability.store import connect

DEFAULT_KEEP_RUNS = 20
_DAY_NS = 86_400 * 10**9


@dataclass
class GcReport:
    runs_dropped: list[str] = field(default_factory=list)
    spans_deleted: int = 0
    checkpoint_rows_deleted: int = 0


def _runs_by_age(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(run_id, newest run-span start_ns) pairs, newest first."""
    rows = conn.execute(
        "SELECT json_extract(attrs, '$.\"run.id\"') AS rid, MAX(start_ns) AS latest "
        "FROM spans WHERE name = 'run' AND rid IS NOT NULL "
        "GROUP BY rid ORDER BY latest DESC"
    )
    return [(str(r[0]), int(r[1])) for r in rows]


def _drop_spans(conn: sqlite3.Connection, run_ids: list[str]) -> int:
    placeholders = ",".join("?" * len(run_ids))
    traces = [
        str(r[0])
        for r in conn.execute(
            "SELECT DISTINCT trace_id FROM spans WHERE name = 'run' "
            f"AND json_extract(attrs, '$.\"run.id\"') IN ({placeholders})",
            run_ids,
        )
    ]
    if not traces:
        return 0
    placeholders = ",".join("?" * len(traces))
    cur = conn.execute(f"DELETE FROM spans WHERE trace_id IN ({placeholders})", traces)
    conn.commit()
    return cur.rowcount


def _drop_checkpoints(checkpoint_db: Path, run_ids: list[str]) -> int:
    """Delete dropped runs' rows from every thread_id-keyed table (checkpoints/writes)."""
    if not checkpoint_db.is_file():
        return 0
    deleted = 0
    placeholders = ",".join("?" * len(run_ids))
    with contextlib.closing(sqlite3.connect(checkpoint_db)) as conn:
        tables = [
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        for table in tables:
            cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}
            if "thread_id" not in cols:
                continue
            cur = conn.execute(
                f"DELETE FROM {table} WHERE thread_id IN ({placeholders})", run_ids
            )
            deleted += cur.rowcount
        conn.commit()
        conn.execute("VACUUM")
    return deleted


def gc_stores(
    span_db: Path,
    checkpoint_db: Path,
    *,
    keep_runs: int | None = None,
    keep_days: int | None = None,
    now_ns: int | None = None,
) -> GcReport:
    """Drop old runs from both stores. Default policy: keep the 20 newest runs.

    `keep_runs` keeps the N newest; `keep_days` keeps runs newer than the
    cutoff; given both, a run survives only if it satisfies both.
    """
    if keep_runs is None and keep_days is None:
        keep_runs = DEFAULT_KEEP_RUNS
    now = time.time_ns() if now_ns is None else now_ns

    report = GcReport()
    with contextlib.closing(connect(span_db)) as conn:
        runs = _runs_by_age(conn)
        dropped: list[str] = []
        for rank, (run_id, latest_ns) in enumerate(runs):
            too_many = keep_runs is not None and rank >= keep_runs
            too_old = keep_days is not None and latest_ns < now - keep_days * _DAY_NS
            if too_many or too_old:
                dropped.append(run_id)
        if dropped:
            report.runs_dropped = dropped
            report.spans_deleted = _drop_spans(conn, dropped)
            conn.execute("VACUUM")
    if report.runs_dropped:
        report.checkpoint_rows_deleted = _drop_checkpoints(checkpoint_db, report.runs_dropped)
    return report
