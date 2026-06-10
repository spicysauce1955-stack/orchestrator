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
