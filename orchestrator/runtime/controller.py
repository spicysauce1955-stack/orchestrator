"""The mode seam (spec §6): declarative now, agentic specced-not-built."""

from __future__ import annotations

from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Mode
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler


def make_controller(
    mode: Mode,
    workspace: Workspace,
    adapter: HarnessAdapter | HarnessRegistry,
    repo: Path,
    *,
    checkpoint_db=None,
) -> DeterministicScheduler:
    # `adapter` may be a bare HarnessAdapter (pre-M6a) or a HarnessRegistry; the
    # scheduler normalizes a bare adapter via HarnessRegistry.single.
    if mode == Mode.agentic:
        raise NotImplementedError("agentic mode (AgenticSupervisor) is specced, not built")
    return DeterministicScheduler(workspace, adapter, repo, checkpoint_db=checkpoint_db)
