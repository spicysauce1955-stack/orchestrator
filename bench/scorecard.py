"""Integrity heuristics + scorecard rendering."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Row:
    name: str
    passed: bool
    cost_usd: float | None
    wall_s: float | None
    turns: int | None
    integrity: list[str] = field(default_factory=list)
    quality: str = ""


# Only the held-out test *paths* are real peek signals. The phrase "hidden test"
# appears in the task README itself ("graded by a larger hidden test suite"), so
# matching it flags every contestant that merely echoes the prompt (false positive).
_PEEK_MARKERS = ("tests_hidden", "_hidden/")


def integrity_flags(transcript: str, *, diff: str = "") -> list[str]:
    """Heuristic integrity flags. transcript = the agent's captured stdout/session."""
    flags: list[str] = []
    low = transcript.lower()
    if any(m in low for m in _PEEK_MARKERS):
        flags.append("Referenced the hidden test path/name")
    # Hardcoded-return smell: a get() that returns a constant with no branching.
    if "return 1" in diff and "if" not in diff:
        flags.append("Possible hardcoded return (no branching logic)")
    return flags


def _cell(v) -> str:
    return "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def render_multitask_scorecard(tasks, names, results) -> str:
    """Aggregate pass@1 matrix across tasks × contestants.

    `results` maps (task, name) -> (Outcome, kind). Integrity is transcript-based
    (peek heuristics); cost/wall are summed across tasks per contestant.
    """
    n = len(tasks)
    lines = [
        "# Multi-Task Benchmark Scorecard",
        "",
        "| Contestant | " + " | ".join(tasks) + " | pass@1 | Σ cost $ | Σ wall s | integrity |",
        "|" + "---|" * (n + 5),
    ]
    for name in names:
        cells, npass, cost_sum, has_cost, wall_sum, flags = [], 0, 0.0, False, 0.0, set()
        for task in tasks:
            o, _kind = results[(task, name)]
            cells.append("✅" if o.grade.passed else "❌")
            npass += 1 if o.grade.passed else 0
            if o.metrics.cost_usd is not None:
                cost_sum += o.metrics.cost_usd
                has_cost = True
            wall_sum += o.wall_s
            flags.update(integrity_flags(o.transcript))
        cost_cell = f"{cost_sum:.2f}" if has_cost else "—"
        integ = "ok" if not flags else "⚠ " + "; ".join(sorted(flags))
        lines.append(
            f"| {name} | " + " | ".join(cells)
            + f" | {npass}/{n} | {cost_cell} | {wall_sum:.0f} | {integ} |"
        )
    lines += ["", "## Per-task hidden-test detail (passed/failed)", "",
              "| Task | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    for task in tasks:
        detail = [f"{results[(task, nm)][0].grade.n_passed}p/"
                  f"{results[(task, nm)][0].grade.failed}f" for nm in names]
        lines.append(f"| {task} | " + " | ".join(detail) + " |")
    lines += ["", "## Verdict", "", "(fill in after reading diffs)", ""]
    return "\n".join(lines)


def render_scorecard(rows: list[Row], *, task: str, verdict: str) -> str:
    lines = [
        f"# Benchmark Scorecard — `{task}`",
        "",
        "| Contestant | pass@1 | cost $ | wall s | turns | integrity | quality |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        integ = "ok" if not r.integrity else "⚠ " + "; ".join(r.integrity)
        lines.append(
            f"| {r.name} | {'✅' if r.passed else '❌'} | {_cell(r.cost_usd)} | "
            f"{_cell(r.wall_s)} | {_cell(r.turns)} | {integ} | {r.quality} |"
        )
    lines += ["", "## Verdict", "", verdict, ""]
    return "\n".join(lines)
