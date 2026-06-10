"""Knowledge miner (spec §8.1): repeated cross-run patterns → candidate lessons.

Seeds the span store with direct row inserts (same idiom as test_gc.py) and
asserts the deterministic detectors. The miner only ever *proposes*: writing
lessons stays behind the auditor-gated MCP write path.
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.knowledge.miner import Candidate, mine, write_candidates
from orchestrator.observability.store import connect

_SPAN_SEQ = 0


def _insert(db: Path, trace: str, name: str, attrs: dict, start_ns: int = 0) -> None:
    global _SPAN_SEQ
    _SPAN_SEQ += 1
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO spans VALUES (?, ?, NULL, ?, ?, ?, ?)",
            (trace, f"{_SPAN_SEQ:016d}", name, start_ns, start_ns + 1, json.dumps(attrs)),
        )
        conn.commit()


def _seed_run(db: Path, run_id: str) -> str:
    """One root `run` span; returns its trace id."""
    trace = f"trace-{run_id}".ljust(32, "0")
    _insert(db, trace, "run", {"run.id": run_id, "pipeline": "p"})
    return trace


def _step(db: Path, trace: str, step_id: str, *, is_error: bool, role: str = "r") -> None:
    _insert(
        db, trace, "step",
        {"step.id": step_id, "step.role": role, "step.is_error": is_error, "step.type": "agent"},
    )


def test_recurring_step_failure_across_runs(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    t1, t2, t3 = (_seed_run(db, r) for r in ("r1", "r2", "r3"))
    _step(db, t1, "implement", is_error=True, role="implementer")
    _step(db, t2, "implement", is_error=True, role="implementer")
    _step(db, t3, "implement", is_error=False, role="implementer")
    _step(db, t1, "plan", is_error=True)  # only one run -> below min_runs
    _step(db, t2, "plan", is_error=False)

    cands = mine(db)

    assert len(cands) == 1
    c = cands[0]
    assert c.kind == "recurring_step_failure"
    assert c.subject == "implement"
    assert set(c.runs) == {"r1", "r2"}
    assert c.count == 2
    assert "implement" in c.text


def test_min_runs_threshold_filters(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    t1, t2 = (_seed_run(db, r) for r in ("r1", "r2"))
    _step(db, t1, "implement", is_error=True)
    _step(db, t2, "implement", is_error=True)

    assert mine(db, min_runs=3) == []


def test_no_failures_no_candidates(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    t1 = _seed_run(db, "r1")
    _step(db, t1, "implement", is_error=False)

    assert mine(db) == []
