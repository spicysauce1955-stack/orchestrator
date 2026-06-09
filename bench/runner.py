"""Benchmark runner: copy task → run contestant → grade against held-out tests."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bench.metrics import Metrics, parse_claude_stream, parse_codex_jsonl

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


@dataclass
class Outcome:
    name: str
    grade: GradeResult
    wall_s: float
    transcript: str
    metrics: Metrics


# An "agent" takes the repo path, mutates it in place, returns its raw transcript.
Agent = Callable[[Path], str]


def run_contestant(name: str, agent: Agent, *, dest_root: Path, hidden_dir: Path) -> Outcome:
    repo = make_repo_copy(name, dest_root=dest_root)
    start = time.monotonic()
    transcript = agent(repo)
    wall_s = time.monotonic() - start
    (repo.parent / "transcript.txt").write_text(transcript)
    g = grade(repo, hidden_dir=hidden_dir)
    return Outcome(name=name, grade=g, wall_s=wall_s, transcript=transcript,
                   metrics=Metrics(None, None, None))


def _prompt() -> str:
    return (TASK_TEMPLATE / "README.md").read_text()


def agent_claude(repo: Path) -> str:
    proc = subprocess.run(
        ["claude", "-p", _prompt(), "--output-format", "stream-json", "--verbose",
         "--permission-mode", "acceptEdits"],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def agent_codex(repo: Path) -> str:
    proc = subprocess.run(
        ["codex", "exec", "-C", str(repo), "-s", "workspace-write", "--json", _prompt()],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def agent_orchestrator(repo: Path) -> str:
    ws = BENCH / "orchestrator_ws" / ".orchestrator"
    env = dict(os.environ)
    env["ORCH_CLAUDE_BIN"] = "claude"
    env["ORCH_SPAN_DB"] = str(repo.parent / "spans.sqlite")
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.cli", "run", "bench",
         "--task", "implement TtlCache per README.md", "--root", str(ws), "--repo", str(repo)],
        cwd=repo, capture_output=True, text=True, env=env, timeout=900,
    )
    transcript = proc.stdout + proc.stderr
    # Agent steps run in isolated worktrees (then torn down); the governed pipeline
    # lands its approved result on the integration branch orch/<run_id>/merge. Parse
    # the real run id from the CLI banner and check that branch's solution into the
    # repo so grade() evaluates what the orchestrator actually produced. A failed run
    # (no merge / non-approve) leaves no branch → the stub is graded (a non-pass).
    m = re.search(r"run ([0-9a-f]+):", transcript)
    run_id = m.group(1) if m else ""
    (repo.parent / "orch_run_id.txt").write_text(run_id)
    if run_id:
        subprocess.run(
            ["git", "checkout", f"orch/{run_id}/merge", "--", "ttl_cache.py"],
            cwd=repo, capture_output=True, text=True,
        )
    return transcript


def main() -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    root = DEFAULT_RESULTS / ts
    hidden = BENCH / "tests_hidden"
    contestants = [
        ("A_orchestrator", agent_orchestrator, "orchestrator"),
        ("B_claude", agent_claude, "claude"),
        ("C_codex", agent_codex, "codex"),
    ]
    outcomes = []
    for name, agent, kind in contestants:
        print(f"=== running {name} ===")
        try:
            o = run_contestant(name, agent, dest_root=root, hidden_dir=hidden)
        except Exception as exc:  # a contestant failing is a RESULT, not a crash
            print(f"{name} FAILED: {exc}")
            o = Outcome(name, GradeResult(False, 0, 1, str(exc)), 0.0, str(exc),
                        Metrics(None, None, None))
        if kind == "claude":
            o.metrics = parse_claude_stream(o.transcript)
        elif kind == "codex":
            o.metrics = parse_codex_jsonl(o.transcript)
        elif kind == "orchestrator":
            o.metrics = parse_claude_stream(o.transcript)  # best-effort; refine from span store
        outcomes.append((o, kind))
        print(f"{name}: pass={o.grade.passed} wall={o.wall_s:.0f}s")
    _emit_scorecard(root, outcomes)


def _emit_scorecard(root: Path, outcomes) -> None:
    from bench.scorecard import Row, integrity_flags, render_scorecard
    rows = []
    for o, _kind in outcomes:
        diff = subprocess.run(["git", "-C", str(root / o.name / "repo"), "diff", "HEAD"],
                              capture_output=True, text=True).stdout
        rows.append(Row(
            name=o.name, passed=o.grade.passed, cost_usd=o.metrics.cost_usd,
            wall_s=o.wall_s, turns=o.metrics.turns,
            integrity=integrity_flags(o.transcript, diff=diff), quality="(fill in: manual rubric)",
        ))
    verdict = "(fill in after reading diffs)"
    (root / "scorecard.md").write_text(render_scorecard(rows, task="TtlCache", verdict=verdict))
    print(f"scorecard → {root / 'scorecard.md'}")


if __name__ == "__main__":  # pragma: no cover
    main()
