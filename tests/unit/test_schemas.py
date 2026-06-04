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
