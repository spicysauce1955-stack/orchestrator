"""End-to-end test: orch run writes spans; orch status reads them (spec §9).

Mirrors tests/integration/test_run_cli.py — same fake harness, same triage
pipeline, same CliRunner / monkeypatch pattern — with ORCH_SPAN_DB added so
the span store lands in a known location we can inspect afterwards.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.observability.query import run_status
from tests.fixtures.repo import make_repo

runner = CliRunner()

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def test_run_writes_spans_readable_by_status(tmp_path, monkeypatch):
    """orch run → spans.sqlite → run_status returns correct view."""
    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)
    db = tmp_path / "spans.sqlite"

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))

    result = runner.invoke(
        app,
        ["run", "triage", "--task", "add a widget", "--root", str(dest), "--repo", str(repo)],
    )
    assert result.exit_code == 0, result.output

    # Extract the run_id printed by the CLI: the token right after "run " on
    # a line like `run <id>: pipeline '...' — ...`.
    run_id = next(
        line.split()[1].rstrip(":")
        for line in result.stdout.splitlines()
        if line.startswith("run ")
    )

    # The span store must exist and be readable.
    assert db.exists(), "ORCH_SPAN_DB was not created by orch run"

    view = run_status(db, run_id)
    assert view is not None, f"run_status returned None for run_id={run_id!r}"
    assert view.run_id == run_id
    assert view.pipeline == "triage"
    assert view.status == "completed"
    # triage has three steps: classify (task), plan (agent), implement (agent)
    step_ids = {s.step_id for s in view.steps}
    assert step_ids, "no steps recorded in the span store"
    # All three triage steps must have been recorded (classify is a task step).
    assert "classify" in step_ids
    assert "plan" in step_ids
    assert "implement" in step_ids
