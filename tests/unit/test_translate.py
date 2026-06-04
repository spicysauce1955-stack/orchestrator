from pathlib import Path

from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps


def _adapter():
    return ClaudeCodeCLIAdapter(binary=["claude"])


def test_translate_permission_mode_and_add_dir():
    caps = ResolvedCaps(permission_mode="acceptEdits")
    flags = _adapter().translate(caps, cwd=Path("/tmp/wt"))
    assert "--permission-mode" in flags
    assert "acceptEdits" in flags
    assert "--add-dir" in flags
    assert "/tmp/wt" in flags


def test_translate_allowed_and_disallowed_tools():
    caps = ResolvedCaps(
        allowed_tools=("Read", "Grep"),
        disallowed_tools=("Edit", "Write"),
        permission_mode="default",
    )
    flags = _adapter().translate(caps)
    i = flags.index("--allowedTools")
    assert flags[i + 1] == "Read,Grep"
    j = flags.index("--disallowedTools")
    assert flags[j + 1] == "Edit,Write"


def test_translate_omits_empty_tool_flags():
    caps = ResolvedCaps(permission_mode="default")
    flags = _adapter().translate(caps)
    assert "--allowedTools" not in flags
    assert "--disallowedTools" not in flags


def test_translate_no_cwd_omits_add_dir():
    caps = ResolvedCaps(permission_mode="default")
    flags = _adapter().translate(caps, cwd=None)
    assert "--add-dir" not in flags
