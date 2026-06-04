"""Per-agent-step git worktree isolation (spec §6).

Each agent step runs in its own worktree on its own branch so edits never
touch the base checkout. Credential exclusion / config read-only are enforced
via ResolvedCaps (safety layer), not here.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str


class WorktreeError(RuntimeError):
    """Raised when a git worktree operation fails."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def create_worktree(repo: Path, branch: str, base: str = "HEAD") -> Worktree:
    """Create a worktree for `branch` (new branch off `base`) under `repo/.worktrees/`."""
    repo = Path(repo)
    safe = branch.replace("/", "-")
    path = repo / ".worktrees" / safe
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, str(path), base)
    return Worktree(path=path, branch=branch)


def remove_worktree(repo: Path, worktree: Worktree) -> None:
    """Remove the worktree and delete its branch. Best-effort, idempotent."""
    repo = Path(repo)
    _git(repo, "worktree", "remove", "--force", str(worktree.path))
    # Branch deletion is best-effort: it may already be gone.
    proc = subprocess.run(
        ["git", "branch", "-D", worktree.branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    _ = proc  # ignore failure (branch may not exist)
