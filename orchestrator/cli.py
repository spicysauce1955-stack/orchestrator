"""orch CLI. M1 implements `compile`; run/status/resume are later milestones."""

from __future__ import annotations

from pathlib import Path

import typer

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import ConfigError, load_workspace

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
    typer.echo(f"`orch {name}` is not implemented in M1 (config + compiler only).")
    raise typer.Exit(2)


@app.command()
def run(pipeline: str = typer.Argument(...)) -> None:
    """Execute a pipeline (later milestone)."""
    _not_implemented("run")


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
