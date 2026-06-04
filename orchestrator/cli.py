"""orch CLI. M1 implements `compile`; M2 implements `run --only`."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import ConfigError, load_workspace
from orchestrator.config.schemas import StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import SPAN_RUN, configure_tracing, get_tracer
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext

app = typer.Typer(help="Declarative multi-vendor coding-agent orchestrator.")


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


def _not_implemented(name: str) -> None:
    typer.echo(f"`orch {name}` is not implemented until a later milestone.")
    raise typer.Exit(2)


@app.command()
def run(
    pipeline: str = typer.Argument(..., help="Pipeline name (file stem under pipelines/)."),
    task: str = typer.Option("", "--task", help="Value for the pipeline's `task` input."),
    only: str = typer.Option(
        "", "--only", help="Run exactly one agent step by id (required in M2)."
    ),
    root: Path = typer.Option(
        Path(".orchestrator"), "--root", help="Path to the .orchestrator/ workspace."
    ),
    repo: Path = typer.Option(
        Path("."), "--repo", help="Git repo to create the step's worktree in."
    ),
) -> None:
    """Run a pipeline. M2 runs a single agent step via --only; the full DAG is M3."""
    if not only:
        typer.echo("error: M2 can only run one agent step — pass --only <step_id>.")
        raise typer.Exit(2)

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

    step = next((s for s in pipe.steps if s.id == only), None)
    if step is None:
        typer.echo(f"error: pipeline '{pipeline}' has no step '{only}'.")
        raise typer.Exit(1)
    if step.type is not StepType.agent:
        typer.echo(
            f"error: step '{only}' is type '{step.type.value}'; M2 runs agent steps only."
        )
        raise typer.Exit(2)

    configure_tracing(exporter=None)
    adapter = ClaudeCodeCLIAdapter()  # honors $ORCH_CLAUDE_BIN
    ctx = RunContext(run_id=uuid.uuid4().hex[:8], inputs={"task": task})

    async def _go():
        tracer = get_tracer()
        with tracer.start_as_current_span(SPAN_RUN) as run_span:
            run_span.set_attribute("run.id", ctx.run_id)
            run_span.set_attribute("pipeline", pipeline)
            return await run_agent_step(workspace, pipe, step, ctx, repo=repo, adapter=adapter)

    artifact = asyncio.run(_go())

    status_word = "ERROR" if artifact.is_error else "OK"
    typer.echo(f"{status_word}: step '{artifact.step_id}' (run {ctx.run_id})")
    typer.echo(f"  branch: {artifact.branch}")
    typer.echo(f"  cost: ${artifact.cost_usd:.4f} ({artifact.tokens} tokens)")
    if artifact.diff:
        typer.echo(f"  diff: {len(artifact.diff.splitlines())} line(s) changed")
    typer.echo("---- output ----")
    typer.echo(artifact.output)
    if artifact.is_error:
        raise typer.Exit(1)


@app.command()
def status(run_id: str = typer.Argument(...)) -> None:
    """Show a run's status (later milestone)."""
    _not_implemented("status")


@app.command()
def resume(run_id: str = typer.Argument(...)) -> None:
    """Resume an interrupted run (later milestone)."""
    _not_implemented("resume")


if __name__ == "__main__":  # pragma: no cover
    app()
