"""Knowledge provider (spec §8): core injection + on-demand MCP wiring.

Two jobs, both consumed by `run_agent_step`:
- `inject_core`: copy core.yaml `inject` files into the agent's worktree so the
  harness reads them (AGENTS.md + pinned docs). Always read, never writable.
- `build_knowledge_mcp` (added next): turn a role's resolved knowledge caps into
  an McpServer descriptor; deny-wins write gating lives there.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator.config.schemas import CoreKnowledge


def inject_core(core: CoreKnowledge | None, root: Path, dest: Path) -> list[str]:
    """Copy each `inject` file from `root` into `dest`. Returns injected rel paths."""
    if core is None:
        return []
    injected: list[str] = []
    for rel in core.inject:
        src = root / rel
        if not src.is_file():
            continue  # missing source: skip (validated softly; not fatal in MVP)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        injected.append(rel)
    return injected
