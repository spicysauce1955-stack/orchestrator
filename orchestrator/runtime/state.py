"""Typed run state threaded through execution (spec §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict


class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


CHECKPOINT_SERDE_MODULES = [
    ("orchestrator.runtime.state", "RunContext"),
    ("orchestrator.runtime.state", "Artifact"),
    ("orchestrator.runtime.state", "RunStatus"),
]


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
    attempts: dict[str, int] = field(default_factory=dict)

    pipeline_name: str = ""
    status: RunStatus = RunStatus.RUNNING
    gate_decisions: dict[str, str] = field(default_factory=dict)
    pending_interrupt: dict | None = None

    def record(self, artifact: Artifact) -> None:
        self.artifacts[artifact.step_id] = artifact
        self.total_cost_usd += artifact.cost_usd


class GraphState(TypedDict, total=False):
    """Executable-graph state: a single shared RunContext threaded through nodes.

    MVP pipelines are linear, so one mutable RunContext under one key is safe.
    Parallel/best-of-n branches (deferred) would need per-key reducers.
    """

    ctx: RunContext
