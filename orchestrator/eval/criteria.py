"""success_criteria runner + test-count gate (spec §6, §9)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# pytest-style test functions: `def test_...` / `async def test_...`.
_TEST_FN = re.compile(r"^[ \t]*(async[ \t]+)?def[ \t]+test\w*[ \t]*\(", re.MULTILINE)
_SKIP_DIRS = {".git", ".worktrees", ".venv", "__pycache__", "node_modules"}


def run_success_criteria(criteria: str, cwd: Path) -> tuple[bool, str]:
    """Run the success_criteria shell command in `cwd`. Returns (ok, combined output)."""
    proc = subprocess.run(criteria, cwd=cwd, shell=True, capture_output=True, text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def count_tests(root: Path) -> int:
    """Count pytest-style test functions under `root` (heuristic, MVP)."""
    root = Path(root)
    root_parts = len(root.parts)
    total = 0
    for path in root.rglob("*.py"):
        # Only inspect parts that are relative to root (skip ancestor dirs).
        if any(part in _SKIP_DIRS for part in path.parts[root_parts:]):
            continue
        name = path.name
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        total += len(_TEST_FN.findall(text))
    return total


def test_count_regressed(before: int, after: int) -> bool:
    """True when the post-edit test count is lower than the pre-edit baseline."""
    return after < before
