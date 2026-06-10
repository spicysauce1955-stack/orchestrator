"""Knowledge provider (spec §8): core injection + on-demand MCP wiring.

Two jobs, both consumed by `run_agent_step`:
- `inject_core`: copy core.yaml `inject` files into the agent's worktree so the
  harness reads them (AGENTS.md + pinned docs). Always read, never writable.
- `build_knowledge_mcp` (added next): turn a role's resolved knowledge caps into
  an McpServer descriptor; deny-wins write gating lives there.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from opentelemetry import trace

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import CoreKnowledge
from orchestrator.harness.adapter import McpServer
from orchestrator.observability.store import span_db_path
from orchestrator.safety.capabilities import ResolvedCaps


def inject_core(core: CoreKnowledge | None, root: Path, dest: Path) -> list[str]:
    """Copy each `inject` file from `root` into `dest`. Returns injected rel paths.

    Files listed in `inject` that are absent from `root` are silently skipped
    (soft validation — a misconfigured path shortens the result, never raises).
    """
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


def build_knowledge_mcp(
    workspace: Workspace, caps: ResolvedCaps, root: Path, *, step_id: str = ""
) -> list[McpServer]:
    """ResolvedCaps knowledge grants -> an McpServer (or none). Deny-wins gating:
    the write target is set ONLY when `caps.knowledge_write` is non-empty.

    Called inside the step span: the active trace context is threaded to the
    server via env so its mcp.call / knowledge.write spans land in the run's
    trace in the span store (the server is a harness-spawned subprocess and
    cannot share our OTel provider)."""
    if not caps.knowledge_read and not caps.knowledge_write:
        return []

    sources: list[str] = []
    for name in caps.knowledge_read:
        src = workspace.knowledge_sources.get(name)
        if src is not None:
            sources.extend(src.sources)

    env: dict[str, str] = {
        "ORCH_KB_SOURCES": json.dumps(_dedup(sources)),
        "ORCH_KB_ROOT": str(root),
    }
    if caps.knowledge_write:
        # MVP: write appends to the first granted writable source (spec §8 -> lessons.md).
        first = caps.knowledge_write[0]
        wsrc = workspace.knowledge_sources.get(first)
        target_rel = (
            wsrc.sources[0]
            if wsrc and wsrc.sources
            else ".orchestrator/knowledge/lessons.md"
        )
        env["ORCH_KB_WRITE_TARGET"] = str(root / target_rel)

    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        env["ORCH_SPAN_DB"] = str(span_db_path(root))
        env["ORCH_SPAN_TRACE"] = format(ctx.trace_id, "032x")
        env["ORCH_SPAN_PARENT"] = format(ctx.span_id, "016x")
        env["ORCH_KB_STEP"] = step_id

    return [McpServer(
        name="knowledge",
        command=sys.executable,
        args=["-m", "orchestrator.knowledge.mcp_server"],
        env=env,
    )]


def _dedup(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for i in items:
        seen.setdefault(i, None)
    return list(seen)
