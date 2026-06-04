import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app
from tests.fixtures.repo import make_repo

runner = CliRunner()

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = Path("examples/feature-pipeline/.orchestrator")


def test_run_only_plan_step(tmp_path, monkeypatch):
    # Copy the example workspace into a throwaway git repo so the worktree
    # is created in an isolated place.
    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))

    result = runner.invoke(
        app,
        [
            "run",
            "feature",
            "--task",
            "add a feature",
            "--only",
            "plan",
            "--root",
            str(dest),
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "plan" in result.output
    assert "cost" in result.output.lower()


def test_run_requires_only_in_m2(tmp_path):
    result = runner.invoke(app, ["run", "feature"])
    # Without --only, M2 cannot run the full DAG yet.
    assert result.exit_code == 2
    assert "only" in result.output.lower()
