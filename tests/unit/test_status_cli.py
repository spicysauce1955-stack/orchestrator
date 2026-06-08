from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.observability.spans import (
    SPAN_MESSAGE,
    SPAN_RUN,
    SPAN_SESSION,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)
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


def _seed_full(db: Path) -> None:
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r3")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as impl:
            impl.set_attribute("step.id", "implement")
            impl.set_attribute("step.role", "implementer")
            impl.set_attribute("step.is_error", False)
            with tracer.start_as_current_span(SPAN_SESSION) as sess:
                sess.set_attribute("cost.usd", 0.25)
                sess.set_attribute("cost.tokens", 800)
        with tracer.start_as_current_span(SPAN_MESSAGE) as m:
            m.set_attribute("msg.from", "implement")
            m.set_attribute("msg.to", "orchestrator")
            m.set_attribute("msg.kind", "question")
            m.set_attribute("msg.body", "which db?")


def test_metrics_renders_costs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed_full(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["metrics", "r3"])
    assert result.exit_code == 0
    assert "0.25" in result.stdout
    assert "800" in result.stdout
    assert "implement" in result.stdout


def test_memory_renders_messages(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed_full(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["memory", "r3"])
    assert result.exit_code == 0
    assert "question" in result.stdout
    assert "which db?" in result.stdout
    assert "implement" in result.stdout and "orchestrator" in result.stdout


def test_metrics_unknown_run_exits_1(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed_full(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["metrics", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.stdout


def test_memory_unknown_run_exits_1(tmp_path: Path, monkeypatch) -> None:
    # An unknown run is distinguishable from a known run with no messages
    # (M6d follow-up: memory probes run_status to disambiguate).
    db = tmp_path / "spans.sqlite"
    _seed_full(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["memory", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.stdout


def test_memory_known_run_without_messages_exits_0(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)  # run "r1" exists but emits no `message` spans
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))
    result = runner.invoke(app, ["memory", "r1"])
    assert result.exit_code == 0
    assert "no messages" in result.stdout.lower()
