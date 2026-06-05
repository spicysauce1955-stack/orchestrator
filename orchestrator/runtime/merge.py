"""Merge manager (spec §6): sequential-rebase agent diffs onto base → PR.

MVP merges by re-applying captured agent diffs onto a fresh integration branch
off the base (the diffs were captured off the same base, so a clean apply is the
no-conflict case). A failed `git apply --3way` is a rebase conflict → HITL.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class MergeConflict(RuntimeError):
    """Raised when a captured diff does not apply cleanly onto the current base."""


def base_branch(repo: Path) -> str:
    """The branch the run targets (the repo's current branch)."""
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _conflicted_files(wt: Path) -> list[str]:
    out = _git(wt, "diff", "--name-only", "--diff-filter=U").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def apply_diffs(repo: Path, branch: str, diffs: list[str], *, base: str) -> str:
    """Create `branch` off `base`, apply each diff (3-way), commit. Returns branch.

    Raises MergeConflict (and cleans up the integration worktree) if any diff
    fails to apply. Idempotent: a pre-existing integration worktree/branch is
    removed first so resume/retry starts clean.
    """
    repo = Path(repo)
    safe = branch.replace("/", "-")
    wt = repo / ".worktrees" / safe
    # Clean any stale integration worktree/branch (retry-safe).
    _git(repo, "worktree", "remove", "--force", str(wt))
    _git(repo, "branch", "-D", branch)
    wt.parent.mkdir(parents=True, exist_ok=True)

    res = _git(repo, "worktree", "add", "-b", branch, str(wt), base)
    if res.returncode != 0:
        raise MergeConflict(f"could not create integration branch: {res.stderr.strip()}")
    try:
        for diff in diffs:
            if not diff.strip():
                continue
            proc = subprocess.run(
                ["git", "apply", "--3way", "-"],
                cwd=wt,
                input=diff,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                files = _conflicted_files(wt)
                raise MergeConflict(
                    f"rebase conflict applying diff in {', '.join(files) or '?'}: "
                    f"{proc.stderr.strip()}"
                )
            _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", f"orchestrator: integrate ({branch})")
    except MergeConflict:
        _git(repo, "worktree", "remove", "--force", str(wt))
        _git(repo, "branch", "-D", branch)
        raise
    # Keep the branch; remove the worktree (the branch is what the PR pushes).
    _git(repo, "worktree", "remove", "--force", str(wt))
    return branch
