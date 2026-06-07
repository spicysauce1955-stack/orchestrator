from orchestrator.harness.opencode import build_permission_config
from orchestrator.safety.capabilities import ResolvedCaps


def test_read_only_denies_edit_and_bash():
    cfg = build_permission_config(ResolvedCaps.read_only())
    perm = cfg["permission"]
    assert perm["edit"] == "deny"
    # bash either a flat "deny" or an object whose default denies
    assert perm["bash"] == "deny" or perm["bash"].get("*") == "deny"


def test_edit_role_allows_edit():
    caps = ResolvedCaps(
        allowed_tools=("Edit", "Write"), disallowed_tools=(), permission_mode="acceptEdits"
    )
    cfg = build_permission_config(caps)
    assert cfg["permission"]["edit"] == "allow"


def test_shell_deny_patterns_become_bash_denies():
    caps = ResolvedCaps(
        allowed_tools=("Bash",),
        disallowed_tools=(),
        permission_mode="acceptEdits",
        shell_deny=("rm -rf", "git push --force"),
    )
    bash = build_permission_config(caps)["permission"]["bash"]
    assert isinstance(bash, dict)
    assert bash.get("rm -rf*") == "deny" or bash.get("rm -rf") == "deny"
    assert bash.get("*") in ("allow", "ask")


def test_env_files_are_read_denied():
    cfg = build_permission_config(ResolvedCaps.read_only())
    read = cfg["permission"].get("read", {})
    assert read.get("*.env") == "deny"
