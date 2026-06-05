"""Step executors (spec §6). M3 adds task steps + the success_criteria/retry loop."""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step
from orchestrator.eval.criteria import count_tests, run_success_criteria, test_count_regressed
from orchestrator.eval.verdict import parse_output
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
from orchestrator.runtime.template import render_template
from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities

# Default prompts when a step declares no `prompt`.
_DEFAULT_PROMPTS = {
    "planner": "Create a concise implementation plan for this task:\n\n{task}",
}


def _render_prompt(step: Step, role_name: str | None, ctx: RunContext) -> str:
    """Render a step's prompt with {{...}} templating over inputs + prior outputs."""
    if step.prompt is None:
        default = _DEFAULT_PROMPTS.get(role_name or "", "Work on this task:\n\n{task}")
        return default.format(task=ctx.inputs.get("task", ""))
    return render_template(step.prompt, ctx.inputs, ctx.artifacts)


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


class _Aggregate:
    """Mutable accumulator for one harness drive."""

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.result_text = ""
        self.cost_usd = 0.0
        self.tokens = 0
        self.is_error = False

    @property
    def output(self) -> str:
        return "".join(self.text_parts) or self.result_text


async def _drive_harness(
    adapter: HarnessAdapter,
    caps: ResolvedCaps,
    cwd: Path,
    prompt: str,
    output_schema: dict | None,
    tracer,
) -> _Aggregate:
    """Start a session, stream events into session/tool/file spans, aggregate."""
    agg = _Aggregate()
    session = await adapter.start_session(cwd=cwd, caps=caps, mcp_servers=[])
    with tracer.start_as_current_span(SPAN_SESSION) as sess_span:
        stream = await adapter.prompt(session, prompt, output_schema=output_schema)
        async for ev in stream:
            if isinstance(ev, MessageChunk):
                agg.text_parts.append(ev.text)
            elif isinstance(ev, ToolCall):
                with tracer.start_as_current_span(SPAN_TOOL_CALL) as tc:
                    tc.set_attribute("tool.name", ev.name)
                    tc.set_attribute("tool.status", ev.status)
            elif isinstance(ev, FileEdit):
                with tracer.start_as_current_span(SPAN_FILE_EDIT) as fe:
                    fe.set_attribute("file.path", ev.path)
                    fe.set_attribute("file.kind", ev.kind)
            elif isinstance(ev, Cost):
                agg.cost_usd += ev.usd
                agg.tokens += ev.tokens
                sess_span.set_attribute("cost.usd", ev.usd)
                sess_span.set_attribute("cost.tokens", ev.tokens)
            elif isinstance(ev, Done):
                agg.result_text = ev.result
                agg.is_error = ev.is_error
                sess_span.set_attribute("done.is_error", ev.is_error)
        sess_span.set_attribute("session.handle", session)
    return agg


async def run_agent_step(
    workspace: Workspace,
    pipeline: Pipeline,
    step: Step,
    ctx: RunContext,
    *,
    repo: Path,
    adapter: HarnessAdapter,
) -> Artifact:
    """Run one agent step end-to-end: worktree → harness drive → success_criteria/retry."""
    if step.role is None:
        raise ValueError(f"step '{step.id}' is not an agent step (no role)")
    role = workspace.roles[step.role]
    caps = resolve_capabilities(role, workspace)
    attempt_no = ctx.attempts.get(step.id, 0) + 1
    ctx.attempts[step.id] = attempt_no
    branch = f"orch/{ctx.run_id}/{step.id}/{attempt_no}"

    tracer = get_tracer()
    total_cost = 0.0
    total_tokens = 0
    output = ""
    is_error = False

    worktree = create_worktree(Path(repo), branch=branch)
    baseline_tests = count_tests(worktree.path)
    try:
        with tracer.start_as_current_span(SPAN_STEP) as step_span:
            step_span.set_attribute("step.id", step.id)
            step_span.set_attribute("step.role", step.role)
            step_span.set_attribute("step.harness", role.harness.value)

            base_prompt = _render_prompt(step, step.role, ctx)
            feedback: str | None = None
            for attempt in range(step.max_retries + 1):
                if feedback is None:
                    prompt = base_prompt
                else:
                    prompt = (
                        f"{base_prompt}\n\nThe previous attempt failed"
                        f" `success_criteria`:\n{feedback}\nFix the issues and try again."
                    )
                agg = await _drive_harness(
                    adapter, caps, worktree.path, prompt, step.output_schema, tracer
                )
                total_cost += agg.cost_usd
                total_tokens += agg.tokens
                output = agg.output
                is_error = agg.is_error

                if not step.success_criteria:
                    break
                ok, crit_out = run_success_criteria(step.success_criteria, worktree.path)
                step_span.set_attribute(f"success_criteria.attempt_{attempt}", ok)
                if ok:
                    is_error = False
                    break
                if attempt >= step.max_retries:
                    is_error = True
                    output = f"{output}\n[success_criteria failed after {attempt + 1} attempt(s)]"
                    break
                feedback = crit_out

            diff = _capture_diff(worktree.path)
            # Test-count gate (spec §6): can't go green by deleting tests.
            if step.success_criteria:
                after_tests = count_tests(worktree.path)
                if test_count_regressed(baseline_tests, after_tests):
                    is_error = True
                    output = (
                        f"{output}\n[test-count gate: tests dropped "
                        f"{baseline_tests}->{after_tests}]"
                    )
                step_span.set_attribute("test_count.before", baseline_tests)
                step_span.set_attribute("test_count.after", after_tests)

            output_data, parse_error = parse_output(agg.result_text, step.output_schema)
            if parse_error:
                is_error = True
            step_span.set_attribute("step.is_error", is_error)

        artifact = Artifact(
            step_id=step.id,
            output=output,
            diff=diff,
            branch=branch,
            cost_usd=total_cost,
            tokens=total_tokens,
            is_error=is_error,
            output_data=output_data,
        )
        ctx.record(artifact)
        return artifact
    finally:
        remove_worktree(Path(repo), worktree)


async def run_task_step(
    workspace: Workspace,
    pipeline: Pipeline,
    step: Step,
    ctx: RunContext,
    *,
    repo: Path,
    adapter: HarnessAdapter,
) -> Artifact:
    """Run a `task` step (cheap LLM glue): read-only, no worktree, parse output."""
    if step.merge_strategy is not None:
        raise NotImplementedError(f"merge task step '{step.id}' runs in M5")

    caps = ResolvedCaps.read_only()
    tracer = get_tracer()
    prompt = _render_prompt(step, None, ctx)

    with tracer.start_as_current_span(SPAN_STEP) as step_span:
        step_span.set_attribute("step.id", step.id)
        step_span.set_attribute("step.type", "task")
        agg = await _drive_harness(
            adapter, caps, Path(repo), prompt, step.output_schema, tracer
        )
        output = agg.result_text or agg.output  # task output is the final result text
        output_data, parse_error = parse_output(output, step.output_schema)
        is_error = agg.is_error or parse_error
        step_span.set_attribute("step.is_error", is_error)

    artifact = Artifact(
        step_id=step.id,
        output=output,
        diff="",
        branch="",
        cost_usd=agg.cost_usd,
        tokens=agg.tokens,
        is_error=is_error,
        output_data=output_data,
    )
    ctx.record(artifact)
    return artifact
