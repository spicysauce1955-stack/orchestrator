"""GC for the .orch/ stores (M5/M6d follow-up: span + checkpoint DBs never GC'd).

`gc_stores` drops whole old runs: their span traces from spans.sqlite and
their checkpoint threads (thread_id == run_id) from checkpoints.sqlite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from orchestrator.observability.gc import gc_stores
from orchestrator.observability.store import connect

DAY_NS = 86_400 * 10**9
NOW_NS = 1_000 * DAY_NS


def _seed_run(db: Path, run_id: str, start_ns: int, n_steps: int = 2) -> None:
    """Insert a run trace directly: one root `run` span + n step spans."""
    trace = f"{abs(hash(run_id)) % 10**30:032d}"
    root = f"{run_id}-root".ljust(16, "0")
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO spans VALUES (?, ?, NULL, 'run', ?, ?, ?)",
            (trace, root, start_ns, start_ns + 100,
             json.dumps({"run.id": run_id, "pipeline": "p"})),
        )
        for i in range(n_steps):
            conn.execute(
                "INSERT INTO spans VALUES (?, ?, ?, 'step', ?, ?, ?)",
                (trace, f"{run_id}-s{i}".ljust(16, "0"), root,
                 start_ns + i, start_ns + i + 1, json.dumps({"step.id": f"s{i}"})),
            )
        conn.commit()


def _seed_checkpoints(db: Path, run_ids: list[str]) -> None:
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT, data BLOB)")
    conn.execute("CREATE TABLE writes (thread_id TEXT, idx INTEGER)")
    for rid in run_ids:
        conn.execute("INSERT INTO checkpoints VALUES (?, 'c1', x'00')", (rid,))
        conn.execute("INSERT INTO writes VALUES (?, 0)", (rid,))
    conn.commit()
    conn.close()


def _run_ids(db: Path) -> set[str]:
    with connect(db) as conn:
        return {
            json.loads(r[0]).get("run.id")
            for r in conn.execute("SELECT attrs FROM spans WHERE name = 'run'")
        }


def test_keep_runs_drops_oldest_runs_spans(tmp_path: Path) -> None:
    spans = tmp_path / "spans.sqlite"
    _seed_run(spans, "r-old", start_ns=NOW_NS - 10 * DAY_NS)
    _seed_run(spans, "r-mid", start_ns=NOW_NS - 5 * DAY_NS)
    _seed_run(spans, "r-new", start_ns=NOW_NS - 1 * DAY_NS)

    report = gc_stores(spans, tmp_path / "absent-cp.sqlite", keep_runs=2, now_ns=NOW_NS)

    assert set(report.runs_dropped) == {"r-old"}
    assert report.spans_deleted == 3  # run + 2 steps
    assert _run_ids(spans) == {"r-mid", "r-new"}


def test_keep_days_drops_runs_older_than_cutoff(tmp_path: Path) -> None:
    spans = tmp_path / "spans.sqlite"
    _seed_run(spans, "r-old", start_ns=NOW_NS - 40 * DAY_NS)
    _seed_run(spans, "r-new", start_ns=NOW_NS - 2 * DAY_NS)

    report = gc_stores(spans, tmp_path / "absent-cp.sqlite", keep_days=30, now_ns=NOW_NS)

    assert set(report.runs_dropped) == {"r-old"}
    assert _run_ids(spans) == {"r-new"}


def test_dropped_runs_checkpoint_threads_are_deleted(tmp_path: Path) -> None:
    spans = tmp_path / "spans.sqlite"
    cp = tmp_path / "checkpoints.sqlite"
    _seed_run(spans, "r-old", start_ns=NOW_NS - 10 * DAY_NS)
    _seed_run(spans, "r-new", start_ns=NOW_NS - 1 * DAY_NS)
    _seed_checkpoints(cp, ["r-old", "r-new", "r-unknown"])

    report = gc_stores(spans, cp, keep_runs=1, now_ns=NOW_NS)

    assert set(report.runs_dropped) == {"r-old"}
    assert report.checkpoint_rows_deleted == 2  # one checkpoints + one writes row
    conn = sqlite3.connect(cp)
    remaining = {r[0] for r in conn.execute("SELECT thread_id FROM checkpoints")}
    conn.close()
    # r-unknown has no span record (age unknowable) — left untouched.
    assert remaining == {"r-new", "r-unknown"}


def test_nothing_to_drop_is_a_clean_noop(tmp_path: Path) -> None:
    spans = tmp_path / "spans.sqlite"
    _seed_run(spans, "r-new", start_ns=NOW_NS - 1 * DAY_NS)

    report = gc_stores(spans, tmp_path / "absent-cp.sqlite", keep_runs=5, now_ns=NOW_NS)

    assert report.runs_dropped == []
    assert report.spans_deleted == 0
    assert report.checkpoint_rows_deleted == 0
    assert _run_ids(spans) == {"r-new"}


def test_default_policy_keeps_20_newest_runs(tmp_path: Path) -> None:
    spans = tmp_path / "spans.sqlite"
    for i in range(25):
        _seed_run(spans, f"r{i:02d}", start_ns=NOW_NS - (25 - i) * DAY_NS, n_steps=0)

    report = gc_stores(spans, tmp_path / "absent-cp.sqlite", now_ns=NOW_NS)

    assert set(report.runs_dropped) == {f"r{i:02d}" for i in range(5)}
    assert len(_run_ids(spans)) == 20


def test_cli_gc_reports_dropped_runs(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from orchestrator.cli import app

    spans = tmp_path / "spans.sqlite"
    _seed_run(spans, "r-old", start_ns=NOW_NS - 10 * DAY_NS)
    _seed_run(spans, "r-new", start_ns=NOW_NS - 1 * DAY_NS)
    monkeypatch.setenv("ORCH_SPAN_DB", str(spans))

    result = CliRunner().invoke(app, ["gc", "--keep-runs", "1"])

    assert result.exit_code == 0
    assert "r-old" in result.stdout
    assert _run_ids(spans) == {"r-new"}


def test_cli_gc_noop_message(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from orchestrator.cli import app

    spans = tmp_path / "spans.sqlite"
    _seed_run(spans, "r-new", start_ns=NOW_NS - 1 * DAY_NS)
    monkeypatch.setenv("ORCH_SPAN_DB", str(spans))

    result = CliRunner().invoke(app, ["gc"])

    assert result.exit_code == 0
    assert "nothing to drop" in result.stdout
