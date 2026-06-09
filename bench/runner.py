"""Benchmark runner: copy task → run contestant → grade against held-out tests.

Multi-task: each task lives in bench/tasks/<task>/{template,reference,tests_hidden}.
The runner runs every contestant on every task and aggregates pass@1.
"""
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
TASKS_DIR = BENCH / "tasks"
DEFAULT_RESULTS = BENCH / "results"


def task_names() -> list[str]:
    """Task names to run (a dir under tasks/ with a template/).

    Honors $ORCH_BENCH_TASKS (comma-separated) to run a subset — e.g. only the
    harder tasks — without moving files. Unknown names are ignored.
    """
    all_tasks = sorted(p.name for p in TASKS_DIR.iterdir() if (p / "template").is_dir())
    subset = os.environ.get("ORCH_BENCH_TASKS", "").strip()
    if subset:
        wanted = [t.strip() for t in subset.split(",") if t.strip()]
        return [t for t in wanted if t in all_tasks]
    return all_tasks


def template_dir(task: str) -> Path:
    return TASKS_DIR / task / "template"


def hidden_dir(task: str) -> Path:
    return TASKS_DIR / task / "tests_hidden"


def make_repo_copy(task: str, name: str, *, dest_root: Path | None = None) -> Path:
    """Copy a task's template into a fresh git repo and return its path."""
    root = dest_root or DEFAULT_RESULTS
    repo = root / task / name / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(template_dir(task), repo)

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


# An "agent" takes (task, repo), mutates the repo in place, returns its raw transcript.
Agent = Callable[[str, Path], str]


def run_contestant(
    task: str, name: str, agent: Agent, *, dest_root: Path, hidden_dir: Path
) -> Outcome:
    repo = make_repo_copy(task, name, dest_root=dest_root)
    start = time.monotonic()
    transcript = agent(task, repo)
    wall_s = time.monotonic() - start
    (repo.parent / "transcript.txt").write_text(transcript)
    g = grade(repo, hidden_dir=hidden_dir)
    return Outcome(name=name, grade=g, wall_s=wall_s, transcript=transcript,
                   metrics=Metrics(None, None, None))


def _prompt(task: str) -> str:
    return (template_dir(task) / "README.md").read_text()


def agent_claude(task: str, repo: Path) -> str:
    proc = subprocess.run(
        ["claude", "-p", _prompt(task), "--output-format", "stream-json", "--verbose",
         "--permission-mode", "acceptEdits"],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def agent_codex(task: str, repo: Path) -> str:
    # codex's -s workspace-write sandbox uses bubblewrap, which fails to initialize in
    # this externally-isolated environment (bwrap loopback RTM_NEWADDR). Each contestant
    # already runs in its own throwaway git repo, so we bypass codex's own sandbox.
    # (Fairness caveat: this also grants codex shell/network its sandboxed peers lack.)
    proc = subprocess.run(
        ["codex", "exec", "-C", str(repo), "--dangerously-bypass-approvals-and-sandbox",
         "--json", _prompt(task)],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def agent_orchestrator(task: str, repo: Path) -> str:
    ws = BENCH / "orchestrator_ws" / ".orchestrator"
    env = dict(os.environ)
    env["ORCH_CLAUDE_BIN"] = "claude"
    env["ORCH_SPAN_DB"] = str(repo.parent / "spans.sqlite")
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.cli", "run", "bench",
         "--task", f"implement the stub module described in README.md (task: {task})",
         "--root", str(ws), "--repo", str(repo)],
        cwd=repo, capture_output=True, text=True, env=env, timeout=900,
    )
    transcript = proc.stdout + proc.stderr
    # Agent steps run in isolated worktrees (then torn down); the governed pipeline
    # lands its approved result on the integration branch orch/<run_id>/merge. Parse
    # the real run id from the CLI banner and check that branch's files into the repo so
    # grade() evaluates what the orchestrator actually produced. A failed run (no merge /
    # non-approve) leaves no branch → the stub is graded (a non-pass). Task-agnostic:
    # check out the whole tree from the merge branch (only the module file differs).
    m = re.search(r"run ([0-9a-f]+):", transcript)
    run_id = m.group(1) if m else ""
    (repo.parent / "orch_run_id.txt").write_text(run_id)
    if run_id:
        subprocess.run(
            ["git", "checkout", f"orch/{run_id}/merge", "--", "."],
            cwd=repo, capture_output=True, text=True,
        )
    return transcript


CONTESTANTS: list[tuple[str, Agent, str]] = [
    ("A_orchestrator", agent_orchestrator, "orchestrator"),
    ("B_claude", agent_claude, "claude"),
    ("C_codex", agent_codex, "codex"),
]


def _metrics_for(kind: str, transcript: str) -> Metrics:
    if kind == "codex":
        return parse_codex_jsonl(transcript)
    # claude + orchestrator both emit claude stream-json (orchestrator cost is
    # best-effort here; the span store has the authoritative number).
    return parse_claude_stream(transcript)


def main() -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    root = DEFAULT_RESULTS / ts
    tasks = task_names()
    names = [n for n, _, _ in CONTESTANTS]
    # results[(task, name)] = (Outcome, kind)
    results: dict[tuple[str, str], tuple[Outcome, str]] = {}
    for task in tasks:
        for name, agent, kind in CONTESTANTS:
            print(f"=== {task} / {name} ===")
            try:
                o = run_contestant(task, name, agent, dest_root=root, hidden_dir=hidden_dir(task))
            except Exception as exc:  # a contestant failing is a RESULT, not a crash
                print(f"{task}/{name} FAILED: {exc}")
                o = Outcome(name, GradeResult(False, 0, 1, str(exc)), 0.0, str(exc),
                            Metrics(None, None, None))
            o.metrics = _metrics_for(kind, o.transcript)
            results[(task, name)] = (o, kind)
            print(f"{task}/{name}: pass={o.grade.passed} wall={o.wall_s:.0f}s")
    _emit_scorecard(root, tasks, names, results)


def _emit_scorecard(
    root: Path, tasks: list[str], names: list[str],
    results: dict[tuple[str, str], tuple[Outcome, str]],
) -> None:
    from bench.scorecard import render_multitask_scorecard
    md = render_multitask_scorecard(tasks, names, results)
    (root / "scorecard.md").write_text(md)
    print(f"scorecard → {root / 'scorecard.md'}")


if __name__ == "__main__":  # pragma: no cover
    main()
