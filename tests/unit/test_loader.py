from pathlib import Path

import pytest

from orchestrator.config.loader import ConfigError, load_workspace


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _minimal_workspace(root: Path) -> Path:
    base = root / ".orchestrator"
    _write(base, "config.yaml", "defaults:\n  isolation: worktree\n")
    _write(base, "roles/implementer.yaml", "harness: claude-code\nskills: [test-runner]\n")
    _write(base, "skills/test-runner.yaml", "instructions: Run pytest -q\ntools: [Read]\n")
    _write(base, "knowledge/core.yaml", "inject: [AGENTS.md]\n")
    _write(
        base,
        "pipelines/feature.yaml",
        "steps:\n"
        "  - id: implement\n"
        "    role: implementer\n",
    )
    return base


def test_load_workspace_populates_registries(tmp_path):
    base = _minimal_workspace(tmp_path)
    ws = load_workspace(base)

    assert ws.roles["implementer"].harness.value == "claude-code"
    assert ws.roles["implementer"].name == "implementer"
    assert ws.skills["test-runner"].instructions.startswith("Run pytest")
    assert ws.core_knowledge.inject == ["AGENTS.md"]
    assert "feature" in ws.pipelines
    assert ws.pipelines["feature"].steps[0].id == "implement"


def test_named_knowledge_source_loads(tmp_path):
    base = _minimal_workspace(tmp_path)
    _write(base, "knowledge/repo-conventions.yaml", "sources: [docs/**]\nbackend: lexical\n")
    ws = load_workspace(base)
    assert ws.knowledge_sources["repo-conventions"].sources == ["docs/**"]


def test_dangling_skill_reference_raises(tmp_path):
    base = _minimal_workspace(tmp_path)
    _write(base, "roles/implementer.yaml", "harness: claude-code\nskills: [missing-skill]\n")
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "missing-skill" in str(exc.value)


def test_pipeline_step_role_reference_validated(tmp_path):
    base = _minimal_workspace(tmp_path)
    _write(
        base,
        "pipelines/feature.yaml",
        "steps:\n  - id: implement\n    role: ghost\n",
    )
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "ghost" in str(exc.value)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_workspace(tmp_path / "nope")


# --- best-of-n judge cross-validation (M9) ---


def _bestof_workspace(root: Path, judge_yaml: str, judge_name: str = "reviewer") -> Path:
    base = _minimal_workspace(root)
    _write(base, f"roles/{judge_name}.yaml", judge_yaml)
    _write(
        base,
        "pipelines/bestof.yaml",
        "steps:\n"
        "  - id: implement\n"
        "    role: implementer\n"
        "    best_of: 2\n"
        f"    judge: {judge_name}\n",
    )
    return base


def test_judge_role_must_exist(tmp_path: Path) -> None:
    base = _minimal_workspace(tmp_path)
    _write(
        base,
        "pipelines/bestof.yaml",
        "steps:\n"
        "  - id: implement\n"
        "    role: implementer\n"
        "    best_of: 2\n"
        "    judge: nope\n",
    )
    with pytest.raises(ConfigError, match="unknown judge role 'nope'"):
        load_workspace(base)


def test_judge_role_must_be_read_only(tmp_path: Path) -> None:
    base = _bestof_workspace(tmp_path, "harness: claude-code\npermissions: edit\n")
    with pytest.raises(ConfigError, match="read-only"):
        load_workspace(base)


def test_read_only_judge_loads(tmp_path: Path) -> None:
    base = _bestof_workspace(tmp_path, "harness: claude-code\npermissions: read-only\n")
    ws = load_workspace(base)
    assert ws.pipelines["bestof"].steps[0].judge == "reviewer"
