"""Throwaway git repo helper for worktree/executor integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_repo(path: Path) -> Path:
    """Init a git repo at `path` with one commit. Returns the repo path."""
    path.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (path / "README.md").write_text("# test repo\n")
    git("add", "README.md")
    git("commit", "-q", "-m", "initial")
    return path
