"""Benchmark runner: copy task → run contestant → grade against held-out tests."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BENCH = Path(__file__).resolve().parent
TASK_TEMPLATE = BENCH / "task_template"
DEFAULT_RESULTS = BENCH / "results"


def make_repo_copy(name: str, *, dest_root: Path | None = None) -> Path:
    """Copy task_template into a fresh git repo and return its path."""
    root = dest_root or DEFAULT_RESULTS
    repo = root / name / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(TASK_TEMPLATE, repo)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "bench@example.com")
    git("config", "user.name", "bench")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-qm", "task baseline")
    return repo


@dataclass
class GradeResult:
    passed: bool
    n_passed: int
    failed: int
    output: str


def grade(repo: Path, *, hidden_dir: Path) -> GradeResult:
    """Copy held-out tests into the repo, run pytest, parse, then remove them."""
    target = repo / "_hidden"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(hidden_dir, target)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "_hidden", "-p", "no:cacheprovider"],
            cwd=repo, capture_output=True, text=True,
        )
    finally:
        shutil.rmtree(target, ignore_errors=True)
    out = proc.stdout + proc.stderr
    n_passed = _count(out, "passed")
    failed = _count(out, "failed") + _count(out, "error")
    return GradeResult(passed=(proc.returncode == 0 and failed == 0),
                       n_passed=n_passed, failed=failed, output=out)


def _count(text: str, word: str) -> int:
    """Parse pytest's summary line, e.g. '12 passed' / '3 failed'."""
    m = re.search(rf"(\d+) {word}", text)
    return int(m.group(1)) if m else 0
