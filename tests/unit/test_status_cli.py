from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.observability.spans import SPAN_RUN, SPAN_STEP, configure_tracing, get_tracer
from orchestrator.observability.store import SqliteSpanExporter

runner = CliRunner()


def _seed(db: Path) -> None:
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r1")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as plan:
            plan.set_attribute("step.id", "plan")
            plan.set_attribute("step.role", "planner")
            plan.set_attribute("step.is_error", False)


def test_status_renders_run_and_steps(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["status", "r1"])
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "completed" in result.stdout
    assert "plan" in result.stdout


def test_status_unknown_run_exits_1(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["status", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.stdout
