"""Typed run state threaded through execution (spec §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass
class Artifact:
    step_id: str
    output: str
    diff: str
    branch: str
    cost_usd: float
    tokens: int
    is_error: bool
    output_data: dict | None = None


@dataclass
class RunContext:
    run_id: str
    inputs: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    total_cost_usd: float = 0.0

    def record(self, artifact: Artifact) -> None:
        self.artifacts[artifact.step_id] = artifact
        self.total_cost_usd += artifact.cost_usd


class GraphState(TypedDict, total=False):
    """Executable-graph state: a single shared RunContext threaded through nodes.

    MVP pipelines are linear, so one mutable RunContext under one key is safe.
    Parallel/best-of-n branches (deferred) would need per-key reducers.
    """

    ctx: RunContext
