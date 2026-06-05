import subprocess

import pytest

from orchestrator.runtime.merge import MergeConflict, apply_diffs, base_branch


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _diff_for(repo, edits: dict[str, str]) -> str:
    """Produce a reapplyable diff by editing a throwaway worktree off HEAD."""
    wt = repo / ".worktrees" / "tmp"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "HEAD"], cwd=repo, check=True)
    for name, content in edits.items():
        (wt / name).write_text(content)
    subprocess.run(["git", "add", "-A", "-N"], cwd=wt, check=True)
    diff = subprocess.run(["git", "diff"], cwd=wt, capture_output=True, text=True).stdout
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=True)
    return diff


def test_base_branch(tmp_path):
    repo = _repo(tmp_path)
    assert base_branch(repo) == "main"


def test_apply_diffs_clean(tmp_path):
    repo = _repo(tmp_path)
    diff = _diff_for(repo, {"f.txt": "line1\nCHANGED\nline3\n", "new.txt": "hello\n"})
    branch = apply_diffs(repo, "orch/r1/merge", [diff], base="main")
    show = subprocess.run(
        ["git", "show", f"{branch}:new.txt"], cwd=repo, capture_output=True, text=True
    )
    assert show.returncode == 0 and show.stdout == "hello\n"


def test_apply_diffs_conflict_raises(tmp_path):
    repo = _repo(tmp_path)
    diff = _diff_for(repo, {"f.txt": "line1\nMINE\nline3\n"})
    (repo / "f.txt").write_text("line1\nTHEIRS\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "advance"], cwd=repo, check=True)
    with pytest.raises(MergeConflict) as exc:
        apply_diffs(repo, "orch/r1/merge", [diff], base="main")
    assert "f.txt" in str(exc.value)
