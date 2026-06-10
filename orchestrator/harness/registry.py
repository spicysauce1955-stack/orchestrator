"""HarnessRegistry: resolve a HarnessAdapter per role's harness (spec §5).

The swappability payoff: a pipeline can run different steps on different
harnesses. A bare adapter wraps to a `.single()` registry for back-compat with
the single-adapter call sites that predate M6a.
"""

from __future__ import annotations

from orchestrator.config.schemas import Harness
from orchestrator.harness.adapter import HarnessAdapter


class HarnessRegistry:
    def __init__(
        self,
        adapters: dict[Harness, HarnessAdapter] | None = None,
        *,
        default: Harness = Harness.claude_code,
    ) -> None:
        self._adapters: dict[Harness, HarnessAdapter] = dict(adapters or {})
        self._single: HarnessAdapter | None = None
        self._default = default

    @classmethod
    def single(cls, adapter: HarnessAdapter) -> HarnessRegistry:
        """All harnesses resolve to one adapter (back-compat / tests)."""
        reg = cls()
        reg._single = adapter
        return reg

    @classmethod
    def from_env(cls) -> HarnessRegistry:
        """Default production registry: real adapters honoring $ORCH_*_BIN."""
        from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
        from orchestrator.harness.codex import CodexCLIAdapter
        from orchestrator.harness.opencode import OpenCodeCLIAdapter

        return cls(
            {
                Harness.claude_code: ClaudeCodeCLIAdapter(),
                Harness.codex: CodexCLIAdapter(),
                Harness.opencode: OpenCodeCLIAdapter(),
            }
        )

    def adapter_for(self, harness: Harness) -> HarnessAdapter:
        if self._single is not None:
            return self._single
        if harness not in self._adapters:
            raise KeyError(f"no adapter registered for harness '{harness.value}'")
        return self._adapters[harness]

    def default_adapter(self) -> HarnessAdapter:
        return self.adapter_for(self._default)
