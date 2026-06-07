"""Step executors (spec §6).

M3 added task steps + the success_criteria/retry inner loop. M4 added agent-step
verdict parsing (output_data from the harness result), the test-count gate, and the
per-step attempt counter + /{attempt} branch suffix (cycle re-entry safe).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from langgraph.types import interrupt

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.eval.criteria import count_tests, run_success_criteria, test_count_regressed
from orchestrator.eval.verdict import parse_output
from orchestrator.harness.adapter import HarnessAdapter, McpServer
from orchestrator.harness.events import Cost, Done, FileEdit, MessageChunk, ToolCall
from orchestrator.isolation.worktree import create_worktree, remove_worktree
from orchestrator.knowledge.provider import build_knowledge_mcp, inject_core
from orchestrator.observability.spans import (
    SPAN_FILE_EDIT,
    SPAN_SESSION,
    SPAN_STEP,
    SPAN_TOOL_CALL,
    get_tracer,
)
from orchestrator.runtime.merge import MergeConflict, apply_diffs, base_branch, open_pull_request
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


def _capture_diff(cwd: Path, exclude: tuple[str, ...] = ()) -> str:
    """Diff of all changes in the worktree, including newly created files.

    `git add -A -N` (intent-to-add) registers untracked files so `git diff` emits a
    full patch (with content) for them — required so a captured diff can be
    re-applied by the merge step. `git reset HEAD` is called afterwards to remove
    the intent-to-add entries from the index, leaving the working tree and index
    otherwise untouched.

    `exclude` is an optional tuple of relative paths to omit from the diff (e.g.
    injected core knowledge files that are read-only and must not be merged back).
    """
    subprocess.run(
        ["git", "add", "-A", "-N"], cwd=cwd, capture_output=True, text=True
    )
    pathspec: list[str] = []
    if exclude:
        pathspec = ["--", ".", *(f":(exclude){p}" for p in exclude)]
    diff = subprocess.run(
        ["git", "diff", *pathspec], cwd=cwd, capture_output=True, text=True
    ).stdout
    subprocess.run(["git", "reset", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return diff


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
    mcp_servers: Sequence[McpServer] = (),
) -> _Aggregate:
    """Start a session, stream events into session/tool/file spans, aggregate."""
    agg = _Aggregate()
    session = await adapter.start_session(cwd=cwd, caps=caps, mcp_servers=list(mcp_servers))
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
    # Knowledge provider (spec §8): inject core files into the agent's cwd (the
    # worktree) and build the gated MCP server from this role's resolved caps.
    # Write target (if any) is rooted at the REAL repo, not the discarded worktree,
    # so durable lessons persist past the run (see build_knowledge_mcp).
    injected = tuple(inject_core(workspace.core_knowledge, Path(repo), worktree.path))
    mcp_servers = build_knowledge_mcp(workspace, caps, Path(repo))
    baseline_tests = count_tests(worktree.path)
    try:
        with tracer.start_as_current_span(SPAN_STEP) as step_span:
            step_span.set_attribute("step.id", step.id)
            step_span.set_attribute("step.role", step.role)
            step_span.set_attribute("step.harness", role.harness.value)

            base_prompt = _render_prompt(step, step.role, ctx)
            relayed = ctx.relayed_feedback.pop(step.id, None)
            if relayed:
                base_prompt = (
                    f"{base_prompt}\n\n[Reviewer feedback relayed by the orchestrator]:\n"
                    f"{relayed}\nAddress it in this attempt."
                )
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
                    adapter, caps, worktree.path, prompt, step.output_schema, tracer,
                    mcp_servers=mcp_servers,
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

            diff = _capture_diff(worktree.path, exclude=injected)
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
        raise NotImplementedError(
            f"merge task step '{step.id}' must be dispatched via the scheduler's"
            " run_merge_step (direct run_task_step callers are not supported for merge steps)"
        )

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


def run_gate_step(step: Step, ctx: RunContext) -> str:
    """HITL gate: interrupt() halts+checkpoints the run; on resume returns the decision.

    The payload summarizes the run for the human. The returned value
    ('approve'|'reject') is stored in ctx.gate_decisions for the conditional edge.
    """
    last = next(reversed(ctx.artifacts.values()), None) if ctx.artifacts else None
    payload = {
        "step_id": step.id,
        "prompt": f"Approve step '{step.id}'? Reply approve|reject.",
        "run_id": ctx.run_id,
        "last_output": (last.output[:500] if last else ""),
        "total_cost_usd": ctx.total_cost_usd,
    }
    decision = interrupt(payload)
    decision = "reject" if str(decision).lower() == "reject" else "approve"
    ctx.gate_decisions[step.id] = decision
    return decision


def _terminal_verdict(ctx: RunContext) -> str | None:
    """The last recorded review verdict, if any step produced one."""
    verdict = None
    for art in ctx.artifacts.values():
        if art.output_data and "verdict" in art.output_data:
            verdict = art.output_data["verdict"]
    return verdict


async def run_merge_step(
    workspace,
    pipeline: Pipeline,
    step: Step,
    ctx: RunContext,
    *,
    repo: Path,
    adapter,
) -> Artifact:
    """Merge upstream agent diffs onto base → open PR. Conflict → HITL conflict gate."""
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_STEP) as span:
        span.set_attribute("step.id", step.id)
        span.set_attribute("step.type", "merge")

        verdict = _terminal_verdict(ctx)
        if verdict is not None and verdict != "approve":
            span.set_attribute("merge.blocked_verdict", verdict)
            art = Artifact(
                step_id=step.id,
                output=f"merge refused: review verdict is '{verdict}', not approve",
                diff="",
                branch="",
                cost_usd=0.0,
                tokens=0,
                is_error=True,
            )
            ctx.record(art)
            return art

        diffs = [
            a.diff
            for s in pipeline.steps
            if s.type == StepType.agent and (a := ctx.artifacts.get(s.id)) and a.diff.strip()
        ]
        # Cross-step filesystem isolation means each agent worktree starts fresh off base,
        # so the fake harness (ORCH_FAKE_TOUCH) emits an identical "create <file>" diff in
        # every step. Re-applying byte-identical work is a no-op, not a real conflict;
        # dedup here preserves order while dropping those spurious duplicates. Genuinely
        # different diffs (real conflicts) are distinct strings and are preserved.
        # Drop byte-identical diffs — idempotent re-apply is not a conflict.
        diffs = list(dict.fromkeys(diffs))
        base = base_branch(Path(repo))
        if not diffs:
            art = Artifact(
                step_id=step.id, output="nothing to merge: no agent changes to integrate",
                diff="", branch="", cost_usd=0.0, tokens=0, is_error=False,
                output_data={"pr_url": None, "branch": None, "base": base},
            )
            ctx.record(art)
            return art
        branch = f"orch/{ctx.run_id}/merge"
        try:
            apply_diffs(Path(repo), branch, diffs, base=base)
        except MergeConflict as conflict:
            decision = interrupt({
                "step_id": step.id,
                "kind": "conflict",
                "run_id": ctx.run_id,
                "prompt": (
                    "Merge conflict. Resolve base and reply approve to retry, reject to abort."
                ),
                "detail": str(conflict),
            })
            if str(decision).lower() == "reject":
                art = Artifact(
                    step_id=step.id,
                    output=f"merge aborted on conflict: {conflict}",
                    diff="",
                    branch="",
                    cost_usd=0.0,
                    tokens=0,
                    is_error=True,
                )
                ctx.record(art)
                return art
            # approve → retry once (base presumably resolved by the human).
            try:
                apply_diffs(Path(repo), branch, diffs, base=base)
            except MergeConflict as retry_conflict:
                art = Artifact(
                    step_id=step.id,
                    output=(
                        f"merge still conflicts after resume; base not resolved: {retry_conflict}"
                    ),
                    diff="", branch="", cost_usd=0.0, tokens=0, is_error=True,
                )
                ctx.record(art)
                return art

        pr = open_pull_request(Path(repo), branch, base=base, title=f"orchestrator: {ctx.run_id}")
        span.set_attribute("merge.branch", branch)
        span.set_attribute("merge.pr_url", pr)
        art = Artifact(
            step_id=step.id,
            output=f"opened PR for {branch} -> {base}: {pr}",
            diff="",
            branch=branch,
            cost_usd=0.0,
            tokens=0,
            is_error=False,
            output_data={"pr_url": pr, "branch": branch, "base": base},
        )
        ctx.record(art)
        return art
