from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app

runner = CliRunner()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _good_workspace(root: Path) -> Path:
    base = root / ".orchestrator"
    _write(base, "config.yaml", "defaults:\n  isolation: worktree\n")
    _write(base, "roles/planner.yaml", "harness: claude-code\n")
    _write(
        base,
        "pipelines/feature.yaml",
        "inputs: {task: string}\n"
        "steps:\n"
        "  - id: classify\n"
        "    type: task\n"
        "    prompt: Classify <task>\n"
        "  - id: plan\n"
        "    role: planner\n"
        "    needs: [classify]\n",
    )
    return base


def test_compile_ok_exits_zero(tmp_path):
    base = _good_workspace(tmp_path)
    result = runner.invoke(app, ["compile", "feature", "--root", str(base)])
    assert result.exit_code == 0
    assert "OK" in result.stdout
    assert "classify" in result.stdout


def test_compile_with_errors_exits_one(tmp_path):
    base = _good_workspace(tmp_path)
    # Break it: plan needs a nonexistent step.
    _write(
        base,
        "pipelines/feature.yaml",
        "steps:\n  - id: plan\n    role: planner\n    needs: [ghost]\n",
    )
    result = runner.invoke(app, ["compile", "feature", "--root", str(base)])
    assert result.exit_code == 1
    assert "ghost" in result.stdout


def test_compile_unknown_pipeline_exits_one(tmp_path):
    base = _good_workspace(tmp_path)
    result = runner.invoke(app, ["compile", "nope", "--root", str(base)])
    assert result.exit_code == 1


def test_run_requires_only_flag(tmp_path):
    # M2: `run` without --only exits 2 with a message mentioning "only".
    result = runner.invoke(app, ["run", "feature"])
    assert result.exit_code == 2
    assert "only" in result.stdout.lower()
