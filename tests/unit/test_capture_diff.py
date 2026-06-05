import subprocess
from pathlib import Path

from orchestrator.runtime.executors import _capture_diff


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def test_capture_diff_includes_new_file_content(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "new.txt").write_text("brand new\n")
    (repo / "f.txt").write_text("line1\nCHANGED\nline3\n")
    diff = _capture_diff(repo)
    assert "new.txt" in diff
    assert "brand new" in diff
    assert "CHANGED" in diff


def test_capture_diff_is_reapplyable(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "new.txt").write_text("brand new\n")
    (repo / "f.txt").write_text("line1\nCHANGED\nline3\n")
    diff = _capture_diff(repo)
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
    (repo / "new.txt").unlink()
    proc = subprocess.run(
        ["git", "apply", "--3way", "-"], cwd=repo, input=diff, text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (repo / "new.txt").read_text() == "brand new\n"
