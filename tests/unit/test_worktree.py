import subprocess
from pathlib import Path

from orchestrator.isolation.worktree import Worktree, create_worktree, remove_worktree
from tests.fixtures.repo import make_repo


def _branches(repo: Path) -> str:
    return subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True
    ).stdout


def test_create_worktree_makes_isolated_checkout(tmp_path):
    repo = make_repo(tmp_path / "repo")
    wt = create_worktree(repo, branch="orch/run1/plan")
    assert isinstance(wt, Worktree)
    assert wt.path.is_dir()
    assert (wt.path / "README.md").exists()
    assert wt.branch == "orch/run1/plan"
    assert str(wt.path) in _branches(repo)


def test_remove_worktree_cleans_up(tmp_path):
    repo = make_repo(tmp_path / "repo")
    wt = create_worktree(repo, branch="orch/run1/plan")
    remove_worktree(repo, wt)
    assert not wt.path.exists()
    assert str(wt.path) not in _branches(repo)


def test_worktree_edits_do_not_touch_base(tmp_path):
    repo = make_repo(tmp_path / "repo")
    wt = create_worktree(repo, branch="orch/run1/plan")
    (wt.path / "new.txt").write_text("hello")
    assert not (repo / "new.txt").exists()
