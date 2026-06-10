"""Template library + scaffolder (spec §4.2): curated recipes, `orch init`.

The integrity invariant: every shipped template scaffolds into a workspace
whose every pipeline compiles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import load_workspace
from orchestrator.templates import TemplateError, list_templates, scaffold

EXPECTED = {"bugfix-fast", "mixed-harness", "review-heavy"}


def test_list_templates_returns_curated_set() -> None:
    tpls = list_templates()
    assert [t.name for t in tpls] == sorted(EXPECTED)
    for t in tpls:
        assert t.description  # from template.yaml
        assert (t.path / ".orchestrator").is_dir()


def test_scaffold_copies_workspace(tmp_path: Path) -> None:
    created = scaffold("bugfix-fast", tmp_path)
    assert (tmp_path / ".orchestrator" / "pipelines" / "bugfix-fast.yaml").is_file()
    assert (tmp_path / ".orchestrator" / "roles" / "implementer.yaml").is_file()
    rels = {str(p) for p in created}
    assert ".orchestrator/pipelines/bugfix-fast.yaml" in rels


def test_scaffold_refuses_existing_workspace(tmp_path: Path) -> None:
    (tmp_path / ".orchestrator").mkdir()
    with pytest.raises(TemplateError, match="exists"):
        scaffold("bugfix-fast", tmp_path)


def test_scaffold_force_overwrites(tmp_path: Path) -> None:
    scaffold("bugfix-fast", tmp_path)
    scaffold("review-heavy", tmp_path, force=True)
    assert (tmp_path / ".orchestrator" / "pipelines" / "review-heavy.yaml").is_file()
    # fully replaced, not merged
    assert not (tmp_path / ".orchestrator" / "pipelines" / "bugfix-fast.yaml").exists()


def test_scaffold_unknown_template_names_valid_ones(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="bugfix-fast"):
        scaffold("nope", tmp_path)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_template_scaffolds_and_compiles(name: str, tmp_path: Path) -> None:
    scaffold(name, tmp_path)
    ws = load_workspace(tmp_path / ".orchestrator")
    assert ws.pipelines, f"template {name} ships no pipelines"
    for pipeline in ws.pipelines:
        result = compile_pipeline(ws, pipeline)
        assert result.ok, f"{name}/{pipeline}: {result.errors}"


# --- CLI ---


def _invoke(args):
    from typer.testing import CliRunner

    from orchestrator.cli import app

    return CliRunner().invoke(app, args)


def test_cli_init_scaffolds_default_template(tmp_path: Path) -> None:
    result = _invoke(["init", "--dest", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".orchestrator" / "pipelines" / "review-heavy.yaml").is_file()
    assert "review-heavy" in result.stdout


def test_cli_init_list_prints_templates_and_creates_nothing(tmp_path: Path) -> None:
    result = _invoke(["init", "--list", "--dest", str(tmp_path)])
    assert result.exit_code == 0
    for name in EXPECTED:
        assert name in result.stdout
    assert not (tmp_path / ".orchestrator").exists()


def test_cli_init_unknown_template_fails_with_valid_names(tmp_path: Path) -> None:
    result = _invoke(["init", "--template", "nope", "--dest", str(tmp_path)])
    assert result.exit_code == 1
    assert "bugfix-fast" in result.stdout


def test_cli_init_existing_workspace_advises_force(tmp_path: Path) -> None:
    (tmp_path / ".orchestrator").mkdir()
    result = _invoke(["init", "--dest", str(tmp_path)])
    assert result.exit_code == 1
    assert "--force" in result.stdout


def test_cli_new_requires_and_uses_template(tmp_path: Path) -> None:
    result = _invoke(["new", "--template", "bugfix-fast", "--dest", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".orchestrator" / "pipelines" / "bugfix-fast.yaml").is_file()
