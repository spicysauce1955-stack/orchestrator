"""orch CLI. M1 implements `compile`; M2 implements `run --only`; M3 runs the full pipeline."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import typer

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import ConfigError, load_workspace
from orchestrator.config.schemas import Mode, StepType
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.observability.query import run_messages, run_metrics, run_status
from orchestrator.observability.spans import SPAN_RUN, configure_tracing, get_tracer
from orchestrator.observability.store import SqliteSpanExporter, span_db_path
from orchestrator.runtime.controller import make_controller
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext, RunStatus
from orchestrator.runtime.template import TemplateError

app = typer.Typer(help="Declarative multi-vendor coding-agent orchestrator.")


def _checkpoint_db(repo: Path) -> Path:
    env = os.environ.get("ORCH_CHECKPOINT_DB")
    return Path(env) if env else Path(repo) / ".orch" / "checkpoints.sqlite"


def _span_db(repo: Path) -> Path:
    return span_db_path(repo)


def _print_artifact(artifact, run_id, *, brief: bool = False) -> None:
    status_word = "ERROR" if artifact.is_error else "OK"
    typer.echo(f"{status_word}: step '{artifact.step_id}' (run {run_id})")
    if artifact.branch:
        typer.echo(f"  branch: {artifact.branch}")
    typer.echo(f"  cost: ${artifact.cost_usd:.4f} ({artifact.tokens} tokens)")
    if artifact.output_data:
        typer.echo(f"  output_data: {artifact.output_data}")
    if artifact.diff:
        typer.echo(f"  diff: {len(artifact.diff.splitlines())} line(s) changed")
    if not brief:
        typer.echo("---- output ----")
        typer.echo(artifact.output)


@app.command()
def compile(
    pipeline: str = typer.Argument(..., help="Pipeline name (file stem under pipelines/)."),
    root: Path = typer.Option(
        Path(".orchestrator"), "--root", help="Path to the .orchestrator/ workspace."
    ),
) -> None:
    """Validate and compile a pipeline (no execution)."""
    try:
        workspace = load_workspace(root)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}")
        raise typer.Exit(1) from exc

    result = compile_pipeline(workspace, pipeline)

    for warning in result.warnings:
        typer.echo(f"warning: {warning}")

    if not result.ok:
        for error in result.errors:
            typer.echo(f"error: {error}")
        typer.echo(f"FAILED: pipeline '{pipeline}' did not compile.")
        raise typer.Exit(1)

    typer.echo(f"OK: pipeline '{pipeline}' compiled.")
    typer.echo(f"nodes: {', '.join(result.ir.nodes)}")
    for edge in result.ir.edges:
        arrow = "-?->" if edge.conditional else "-->"
        typer.echo(f"  {edge.source} {arrow} {edge.target}")


@app.command()
def run(
    pipeline: str = typer.Argument(..., help="Pipeline name (file stem under pipelines/)."),
    task: str = typer.Option("", "--task", help="Value for the pipeline's `task` input."),
    only: str = typer.Option(
        "", "--only", help="Run exactly one agent step by id (M2 single-step mode)."
    ),
    root: Path = typer.Option(
        Path(".orchestrator"), "--root", help="Path to the .orchestrator/ workspace."
    ),
    repo: Path = typer.Option(
        Path("."), "--repo", help="Git repo to create the step's worktree in."
    ),
) -> None:
    """Run a pipeline (M3: full DAG) or a single step (--only <step_id>)."""
    try:
        workspace = load_workspace(root)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}")
        raise typer.Exit(1) from exc

    pipe = workspace.pipelines.get(pipeline)
    if pipe is None:
        available = ", ".join(sorted(workspace.pipelines)) or "(none)"
        typer.echo(f"error: unknown pipeline '{pipeline}'; available: {available}")
        raise typer.Exit(1)

    configure_tracing(exporter=SqliteSpanExporter(_span_db(repo)))
    registry = HarnessRegistry.from_env()  # adapters honor $ORCH_*_BIN
    run_id = uuid.uuid4().hex[:8]

    # Single-step mode (M2 behavior, still supported).
    if only:
        step = next((s for s in pipe.steps if s.id == only), None)
        if step is None:
            typer.echo(f"error: pipeline '{pipeline}' has no step '{only}'.")
            raise typer.Exit(1)
        if step.type is not StepType.agent:
            typer.echo(
                f"error: step '{only}' is type '{step.type.value}'; --only runs agent steps."
            )
            raise typer.Exit(2)
        ctx = RunContext(run_id=run_id, inputs={"task": task})
        adapter = registry.adapter_for(workspace.roles[step.role].harness)

        async def _one():
            tracer = get_tracer()
            with tracer.start_as_current_span(SPAN_RUN) as run_span:
                run_span.set_attribute("run.id", run_id)
                run_span.set_attribute("pipeline", pipeline)
                return await run_agent_step(workspace, pipe, step, ctx, repo=repo, adapter=adapter)

        try:
            artifact = asyncio.run(_one())
        except TemplateError as exc:
            typer.echo(f"error: cannot render step '{only}' in isolation: {exc}")
            typer.echo(
                "hint: this step references another step's output — run the full "
                "pipeline (omit --only)."
            )
            raise typer.Exit(1) from exc
        _print_artifact(artifact, run_id)
        if artifact.is_error:
            raise typer.Exit(1)
        return

    # Full-pipeline mode (M3).
    try:
        controller = make_controller(
            pipe.mode, workspace, registry, repo, checkpoint_db=_checkpoint_db(repo)
        )
    except NotImplementedError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(2) from exc

    try:
        ctx = asyncio.run(controller.run(pipe, {"task": task}, run_id))
    except TemplateError as exc:
        typer.echo(f"error: template reference failed during run: {exc}")
        raise typer.Exit(1) from exc

    if ctx.status == RunStatus.PAUSED:
        p = ctx.pending_interrupt or {}
        typer.echo(f"run {run_id}: PAUSED at gate '{p.get('step_id')}'")
        typer.echo(f"  {p.get('prompt', 'approval required')}")
        typer.echo(f"  resume with: orch resume {run_id} --approve   (or --reject)")
        return

    typer.echo(f"run {run_id}: pipeline '{pipeline}' ({len(ctx.artifacts)} steps)")
    any_error = False
    for step in pipe.steps:
        art = ctx.artifacts.get(step.id)
        if art is None:
            continue  # not reached on this path (e.g. conditional branch)
        any_error = any_error or art.is_error
        _print_artifact(art, run_id, brief=True)
    typer.echo(f"total cost: ${ctx.total_cost_usd:.4f}")
    if any_error:
        raise typer.Exit(1)


@app.command()
def status(
    run_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose .orch/ holds the span store."),
) -> None:
    """Show a run's step-by-step status from the span store (spec §9)."""
    view = run_status(_span_db(repo), run_id)
    if view is None:
        typer.echo(f"error: no run '{run_id}' found in the span store.")
        raise typer.Exit(1)
    typer.echo(f"run {view.run_id}: pipeline '{view.pipeline}' — {view.status}")
    for s in view.steps:
        mark = "ERROR" if s.is_error else "ok"
        role = f" [{s.role}]" if s.role else ""
        typer.echo(f"  {mark:5} {s.step_id}{role} ({s.kind})")


@app.command()
def metrics(
    run_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose .orch/ holds the span store."),
) -> None:
    """Show a run's cost/token/duration rollup from the span store (spec §9)."""
    view = run_metrics(_span_db(repo), run_id)
    if view is None:
        typer.echo(f"error: no run '{run_id}' found in the span store.")
        raise typer.Exit(1)
    for m in view.steps:
        typer.echo(
            f"  {m.step_id}: ${m.cost_usd:.4f} ({m.tokens} tokens, {m.duration_ms:.0f} ms)"
        )
    typer.echo(f"total: ${view.total_cost_usd:.4f} ({view.total_tokens} tokens)")


@app.command()
def memory(
    run_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose .orch/ holds the span store."),
) -> None:
    """Show a run's coordination board (message bus log) from the span store."""
    db = _span_db(repo)
    msgs = run_messages(db, run_id)
    if not msgs:
        # run_messages returns [] for both an unknown run and a known run with no
        # messages; probe run_status to tell them apart.
        if run_status(db, run_id) is None:
            typer.echo(f"error: no run '{run_id}' found in the span store.")
            raise typer.Exit(1)
        typer.echo(f"run '{run_id}': no messages recorded.")
        return
    for m in msgs:
        typer.echo(f"  {m.frm} → {m.to} [{m.kind}]: {m.body}")


@app.command()
def resume(
    run_id: str = typer.Argument(...),
    approve: bool = typer.Option(False, "--approve", help="Approve the pending gate."),
    reject: bool = typer.Option(False, "--reject", help="Reject the pending gate."),
    root: Path = typer.Option(Path(".orchestrator"), "--root"),
    repo: Path = typer.Option(Path("."), "--repo"),
) -> None:
    """Resume a run paused at a HITL gate."""
    if approve == reject:
        typer.echo("error: pass exactly one of --approve / --reject.")
        raise typer.Exit(2)
    decision = "approve" if approve else "reject"
    try:
        workspace = load_workspace(root)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}")
        raise typer.Exit(1) from exc
    configure_tracing(exporter=SqliteSpanExporter(_span_db(repo)))
    registry = HarnessRegistry.from_env()
    controller = make_controller(
        Mode.declarative, workspace, registry, repo, checkpoint_db=_checkpoint_db(repo)
    )
    try:
        ctx = asyncio.run(controller.resume(run_id, decision))
    except KeyError as exc:
        typer.echo(f"error: no paused run '{run_id}' found.")
        raise typer.Exit(1) from exc
    if ctx.status == RunStatus.PAUSED:
        p = ctx.pending_interrupt or {}
        typer.echo(f"run {run_id}: PAUSED again at '{p.get('step_id')}' — {p.get('prompt','')}")
        typer.echo(f"  resume with: orch resume {run_id} --approve  (or --reject)")
        return
    typer.echo(f"run {run_id}: {ctx.status.value} ({len(ctx.artifacts)} steps)")
    for art in ctx.artifacts.values():
        _print_artifact(art, run_id, brief=True)
    typer.echo(f"total cost: ${ctx.total_cost_usd:.4f}")
    if any(a.is_error for a in ctx.artifacts.values()):
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
