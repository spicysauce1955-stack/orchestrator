import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app

runner = CliRunner()
FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
GH = Path(__file__).parents[1] / "fixtures" / "fake_gh" / "fake_gh.py"
ROOT = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def test_run_pauses_and_resume_completes(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_GH_BIN", f"{sys.executable} {GH}")
    monkeypatch.setenv("ORCH_CHECKPOINT_DB", str(db))
    common = ["--root", str(ROOT), "--repo", str(repo)]
    res = runner.invoke(app, ["run", "full", "--task", "add x", *common])
    assert res.exit_code == 0, res.output
    assert "paused" in res.output.lower()
    assert "orch resume" in res.output
    run_id = next(
        t for line in res.output.splitlines() if "run " in line.lower()
        for t in line.replace(":", " ").split() if len(t) == 8 and t.isalnum()
    )
    res2 = runner.invoke(app, ["resume", run_id, "--approve", *common])
    assert res2.exit_code == 0, res2.output
    assert "merge" in res2.output.lower()


def test_resume_unknown_run_errors(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    monkeypatch.setenv("ORCH_CHECKPOINT_DB", str(db))
    res = runner.invoke(app, ["resume", "deadbeef", "--approve",
                              "--root", str(ROOT), "--repo", str(repo)])
    assert res.exit_code != 0
    assert "deadbeef" in res.output
