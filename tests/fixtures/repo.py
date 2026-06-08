"""Throwaway git repo helper for worktree/executor integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def init_git_repo(path: Path, *, branch: str = "main") -> Path:
    """Init an empty git repo with test identity configured (no seed commit)."""
    path.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init", "-q", "-b", branch)
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    return path


def commit_all(path: Path, message: str = "base") -> None:
    """Stage everything and commit. Use after seeding files into an init_git_repo."""
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=path, check=True, capture_output=True)


def make_repo(path: Path) -> Path:
    """Init a git repo at `path` with one README commit. Returns the repo path."""
    init_git_repo(path)
    (path / "README.md").write_text("# test repo\n")
    commit_all(path, "initial")
    return path
