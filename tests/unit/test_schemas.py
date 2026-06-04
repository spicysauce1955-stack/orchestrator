import pytest
from pydantic import ValidationError

from orchestrator.config.schemas import (
    Access,
    Budget,
    GitAccess,
    Harness,
    Isolation,
    PermissionProfile,
    StepType,
)


def test_enum_values_match_spec():
    assert Harness.claude_code.value == "claude-code"
    assert Harness.opencode.value == "opencode"
    assert PermissionProfile.read_only.value == "read-only"
    assert Isolation.worktree.value == "worktree"
    assert StepType.agent.value == "agent"


def test_budget_defaults():
    b = Budget()
    assert b.max_usd == 5.0
    assert b.timeout_s == 1800


def test_git_access_defaults_are_safe():
    g = GitAccess()
    assert g.push_to_main is False
    assert g.open_pr is True


def test_access_block_parses_nested_dimensions():
    a = Access.model_validate(
        {
            "filesystem": {"write": ["src/**"], "read_only": [".git"]},
            "shell": {"deny": ["rm -rf"]},
            "git": {"push_to_main": False},
        }
    )
    assert a.filesystem.write == ["src/**"]
    assert a.shell.deny == ["rm -rf"]
    assert a.network is None


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Budget.model_validate({"max_usd": 1, "bogus": True})


def test_role_minimal_requires_harness():
    from orchestrator.config.schemas import PermissionProfile, Role

    r = Role.model_validate({"harness": "claude-code"})
    assert r.harness.value == "claude-code"
    assert r.permissions == PermissionProfile.edit  # default preset
    assert r.model is None
    assert r.skills == []
    assert r.budget.max_usd == 5.0


def test_role_full_parses_access_and_refs():
    from orchestrator.config.schemas import Role

    r = Role.model_validate(
        {
            "harness": "claude-code",
            "model": "opus",
            "permissions": "edit",
            "access": {"filesystem": {"write": ["src/**", "tests/**"]}},
            "skills": ["test-runner"],
            "knowledge": ["repo-conventions"],
            "mcp": ["repo-index"],
            "budget": {"max_usd": 5, "timeout_s": 1800},
        }
    )
    assert r.model == "opus"
    assert r.skills == ["test-runner"]
    assert r.access.filesystem.write == ["src/**", "tests/**"]


def test_role_rejects_unknown_harness():
    from pydantic import ValidationError

    from orchestrator.config.schemas import Role

    with pytest.raises(ValidationError):
        Role.model_validate({"harness": "cursor"})


def test_skill_requires_instructions():
    from orchestrator.config.schemas import Skill

    s = Skill.model_validate(
        {"instructions": "Run pytest -q after each change.", "tools": ["Bash(pytest)", "Read"]}
    )
    assert s.tools == ["Bash(pytest)", "Read"]


def test_core_and_index_knowledge():
    from orchestrator.config.schemas import CoreKnowledge, KnowledgeSource

    core = CoreKnowledge.model_validate({"inject": ["AGENTS.md", "docs/architecture.md"]})
    assert core.inject[0] == "AGENTS.md"

    idx = KnowledgeSource.model_validate({"sources": ["docs/**", "src/**"], "backend": "lexical"})
    assert idx.backend == "lexical"
