"""The orchestrator agent (spec §7): first-class run-owner, coordination only.

MVP scope = shared coordination: run the cheap `classify`/task glue, relay the
review verdict to the implementer on loop-back, and answer worker questions.
It is a coordination LAYER, not a router: the DeterministicScheduler stays the
executor and calls into this agent at its existing seams. LLM calls go through
the orchestrator's own Role (default: read-only Claude Code). Every coordination
action is recorded on the MessageBus as an OTel span.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.agents.message_bus import MessageBus
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Harness, PermissionProfile, Pipeline, Role, Step
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.observability.spans import get_tracer
from orchestrator.runtime.executors import _drive_harness, run_task_step
from orchestrator.runtime.state import Artifact, RunContext
from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities

ORCHESTRATOR_ROLE = "orchestrator"


def _default_orchestrator_role() -> Role:
    """Read-only Claude Code role used when the workspace defines no orchestrator."""
    return Role(name=ORCHESTRATOR_ROLE, harness=Harness.claude_code,
                permissions=PermissionProfile.read_only)


class OrchestratorAgent:
    def __init__(self, *, workspace: Workspace, registry: HarnessRegistry,
                 bus: MessageBus, repo: Path) -> None:
        self.workspace = workspace
        self.registry = registry
        self.bus = bus
        self.repo = Path(repo)
        self.role = workspace.roles.get(ORCHESTRATOR_ROLE) or _default_orchestrator_role()

    def _adapter(self):
        return self.registry.adapter_for(self.role.harness)

    async def run_task(self, pipeline: Pipeline, step: Step, ctx: RunContext) -> Artifact:
        """Run a non-merge task step (the orchestrator's coordination glue, e.g.
        classify) via the unchanged run_task_step, then record a `classify` msg."""
        art = await run_task_step(
            self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self._adapter()
        )
        self.bus.send("orchestrator", "run", "classify", art.output)
        return art

    def relay_verdict(self, verdict_body: str, *, to_step: str, ctx: RunContext) -> None:
        """On loop-back: record the reviewer's verdict for the implementer's next
        prompt and emit an orch→worker `verdict` message span."""
        ctx.relayed_feedback[to_step] = verdict_body
        self.bus.send("orchestrator", to_step, "verdict", verdict_body)

    async def answer(self, question: str, *, from_step: str) -> str:
        """Answer a worker's question (LLM via the orchestrator's Role). Emits a
        worker→orch `question` span then an orch→worker `answer` span."""
        self.bus.send(from_step, "orchestrator", "question", question)
        caps: ResolvedCaps = resolve_capabilities(self.role, self.workspace)
        prompt = (
            "A worker agent is blocked and asked the orchestrator a question.\n"
            f"Worker: {from_step}\nQuestion: {question}\n"
            "Answer concisely so the worker can proceed."
        )
        agg = await _drive_harness(self._adapter(), caps, self.repo, prompt, None, get_tracer())
        answer_text = agg.output or agg.result_text
        self.bus.send("orchestrator", from_step, "answer", answer_text)
        return answer_text
