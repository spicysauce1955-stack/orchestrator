from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import (
    PermissionProfile,
    Role,
    Skill,
)
from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities

EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _ws():
    return load_workspace(EXAMPLE)


def test_read_only_profile_disallows_edit_tools():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["planner"], ws)
    assert "Edit" in caps.disallowed_tools
    assert "Write" in caps.disallowed_tools
    assert caps.permission_mode in ("default", "plan")
    # credential + harness-config paths are always denied for reads
    assert any(".ssh" in p for p in caps.deny_read)
    assert any(".git" in p for p in caps.deny_read)


def test_edit_profile_grants_write_scope():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["implementer"], ws)
    assert "src/**" in caps.write_scope
    assert "tests/**" in caps.write_scope
    assert caps.permission_mode == "acceptEdits"
    # global deny merged with role deny
    assert "rm -rf /" in caps.shell_deny
    assert "git push --force" in caps.shell_deny


def test_skill_tools_are_merged_for_edit_role():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["implementer"], ws)
    # test-runner skill grants Bash(pytest), Read, Edit
    assert "Bash(pytest)" in caps.allowed_tools


def test_skill_edit_tool_clamped_by_read_only_profile():
    # A read-only role must not gain Edit even if a skill grants it (deny-wins).
    role = Role(name="r", harness="claude-code", permissions=PermissionProfile.read_only,
                skills=["test-runner"])
    skill = Skill(name="test-runner", instructions="x", tools=["Edit", "Read"])
    ws = _ws()
    ws.roles["r"] = role
    ws.skills["test-runner"] = skill
    caps = resolve_capabilities(role, ws)
    assert "Edit" not in caps.allowed_tools
    assert "Edit" in caps.disallowed_tools


def test_knowledge_write_only_when_explicitly_granted():
    ws = _ws()
    auditor = resolve_capabilities(ws.roles["auditor"], ws)
    planner = resolve_capabilities(ws.roles["planner"], ws)
    assert "lessons" in auditor.knowledge_write
    assert planner.knowledge_write == ()


def test_never_push_to_main():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["implementer"], ws)
    assert caps.push_to_main is False


def test_resolved_caps_read_only_constructor():
    caps = ResolvedCaps.read_only()
    assert caps.permission_mode in ("default", "plan")
    assert "Edit" in caps.disallowed_tools
