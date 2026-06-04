"""Step executors. M2 implements the AgentStep lifecycle for a single step.

Out of M2 scope (later milestones): success_criteria + retry (M3), the review
loop (M4), knowledge injection (M6), the full DAG controller (M3).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.harness.events import Cost, Done, FileEdit, MessageChunk, ToolCall
from orchestrator.isolation.worktree import create_worktree, remove_worktree
from orchestrator.observability.spans import (
    SPAN_FILE_EDIT,
    SPAN_SESSION,
    SPAN_STEP,
    SPAN_TOOL_CALL,
    get_tracer,
)
from orchestrator.runtime.state import Artifact, RunContext
from orchestrator.safety.capabilities import resolve_capabilities

# Default prompts when a step declares no `prompt` (M2 minimal rendering).
_DEFAULT_PROMPTS = {
    "planner": "Create a concise implementation plan for this task:\n\n{task}",
}


def _render_prompt(step: Step, role_name: str, inputs: dict[str, str]) -> str:
    """Render the step prompt. M2: literal substitution of declared top-level
    input names only (`<task>` → value). Full dataflow templating is M3."""
    template = step.prompt
    if template is None:
        default = _DEFAULT_PROMPTS.get(role_name, "Work on this task:\n\n{task}")
        return default.format(task=inputs.get("task", ""))
    rendered = template
    for name, value in inputs.items():
        rendered = rendered.replace(f"<{name}>", value)
    return rendered


def _capture_diff(cwd: Path) -> str:
    """Diff of tracked changes + names of untracked files in the worktree."""
    tracked = subprocess.run(
        ["git", "diff"], cwd=cwd, capture_output=True, text=True
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout
    if untracked.strip():
        names = "\n".join(f"+++ untracked: {n}" for n in untracked.splitlines())
        tracked = f"{tracked}\n{names}" if tracked else names
    return tracked


async def run_agent_step(
    workspace: Workspace,
    pipeline: Pipeline,
    step: Step,
    ctx: RunContext,
    *,
    repo: Path,
    adapter: HarnessAdapter,
) -> Artifact:
    """Run a single agent step end-to-end (spec §6 AgentStep, M2 subset)."""
    if step.role is None:
        raise ValueError(f"step '{step.id}' is not an agent step (no role)")
    role = workspace.roles[step.role]
    caps = resolve_capabilities(role, workspace)

    branch = f"orch/{ctx.run_id}/{step.id}"
    worktree = create_worktree(Path(repo), branch=branch)

    tracer = get_tracer()
    text_parts: list[str] = []
    result_text = ""
    cost_usd = 0.0
    tokens = 0
    is_error = False

    try:
        with tracer.start_as_current_span(SPAN_STEP) as step_span:
            step_span.set_attribute("step.id", step.id)
            step_span.set_attribute("step.role", step.role)
            step_span.set_attribute("step.harness", role.harness.value)

            prompt = _render_prompt(step, step.role, ctx.inputs)
            session = await adapter.start_session(
                cwd=worktree.path, caps=caps, mcp_servers=[]
            )

            with tracer.start_as_current_span(SPAN_SESSION) as sess_span:
                stream = await adapter.prompt(session, prompt, output_schema=step.output_schema)
                async for ev in stream:
                    if isinstance(ev, MessageChunk):
                        text_parts.append(ev.text)
                    elif isinstance(ev, ToolCall):
                        with tracer.start_as_current_span(SPAN_TOOL_CALL) as tc:
                            tc.set_attribute("tool.name", ev.name)
                            tc.set_attribute("tool.status", ev.status)
                    elif isinstance(ev, FileEdit):
                        with tracer.start_as_current_span(SPAN_FILE_EDIT) as fe:
                            fe.set_attribute("file.path", ev.path)
                            fe.set_attribute("file.kind", ev.kind)
                    elif isinstance(ev, Cost):
                        cost_usd = ev.usd
                        tokens = ev.tokens
                        sess_span.set_attribute("cost.usd", ev.usd)
                        sess_span.set_attribute("cost.tokens", ev.tokens)
                    elif isinstance(ev, Done):
                        result_text = ev.result
                        is_error = ev.is_error
                        sess_span.set_attribute("done.is_error", ev.is_error)
                sess_span.set_attribute("session.handle", session)

            diff = _capture_diff(worktree.path)
            step_span.set_attribute("step.is_error", is_error)

        output = "".join(text_parts) or result_text
        artifact = Artifact(
            step_id=step.id,
            output=output,
            diff=diff,
            branch=branch,
            cost_usd=cost_usd,
            tokens=tokens,
            is_error=is_error,
        )
        ctx.record(artifact)
        return artifact
    finally:
        # M2: worktrees are cleaned up after a step. (Retain-on-failure is M3.)
        # NOTE: diff capture happens BEFORE this cleanup, inside the try block.
        remove_worktree(Path(repo), worktree)
