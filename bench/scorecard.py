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
