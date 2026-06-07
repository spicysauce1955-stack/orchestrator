import pytest

from orchestrator.config.schemas import Harness
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry


def test_single_returns_same_adapter_for_any_harness():
    a = ClaudeCodeCLIAdapter(binary=["x"])
    reg = HarnessRegistry.single(a)
    assert reg.adapter_for(Harness.claude_code) is a
    assert reg.adapter_for(Harness.opencode) is a
    assert reg.default_adapter() is a


def test_explicit_mapping_routes_by_harness():
    claude = ClaudeCodeCLIAdapter(binary=["c"])
    oc = OpenCodeCLIAdapter(binary=["o"])
    reg = HarnessRegistry({Harness.claude_code: claude, Harness.opencode: oc})
    assert reg.adapter_for(Harness.claude_code) is claude
    assert reg.adapter_for(Harness.opencode) is oc


def test_unregistered_harness_raises():
    reg = HarnessRegistry({Harness.claude_code: ClaudeCodeCLIAdapter(binary=["c"])})
    with pytest.raises(KeyError):
        reg.adapter_for(Harness.codex)


def test_from_env_builds_claude_and_opencode(monkeypatch):
    monkeypatch.setenv("ORCH_CLAUDE_BIN", "fakeclaude")
    monkeypatch.setenv("ORCH_OPENCODE_BIN", "fakeoc")
    reg = HarnessRegistry.from_env()
    assert isinstance(reg.adapter_for(Harness.claude_code), ClaudeCodeCLIAdapter)
    assert isinstance(reg.adapter_for(Harness.opencode), OpenCodeCLIAdapter)
