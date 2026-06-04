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


def test_run_full_pipeline(tmp_path, monkeypatch):
    import shutil

    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))

    result = runner.invoke(
        app,
        ["run", "triage", "--task", "add a widget", "--root", str(dest), "--repo", str(repo)],
    )
    assert result.exit_code == 0, result.output
    assert "classify" in result.output
    assert "plan" in result.output
    assert "implement" in result.output
    assert "feature" in result.output  # classify output_data surfaced


def test_run_only_step_with_dataflow_ref_errors_cleanly(tmp_path, monkeypatch):
    # `implement` references {{plan.output}}; run in isolation it cannot resolve.
    # The CLI must report a clean error + hint, not dump a TemplateError traceback.
    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))

    result = runner.invoke(
        app,
        ["run", "triage", "--task", "x", "--only", "implement",
         "--root", str(dest), "--repo", str(repo)],
    )
    assert result.exit_code == 1
    assert "in isolation" in result.output
    assert "omit --only" in result.output
    # no raw traceback leaked
    assert "Traceback" not in result.output
