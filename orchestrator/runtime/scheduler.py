"""DeterministicScheduler: the declarative Controller (spec §6).

Builds an executable LangGraph StateGraph from the pipeline IR with real node
closures and invokes it. A single shared RunContext is threaded through nodes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from orchestrator.agents.message_bus import MessageBus
from orchestrator.agents.orchestrator_agent import OrchestratorAgent
from orchestrator.compile.compiler import wire_edges
from orchestrator.compile.ir import build_ir
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.eval.verdict import Verdict
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.observability.spans import SPAN_RUN, get_tracer
from orchestrator.runtime.executors import (
    run_agent_step,
    run_gate_step,
    run_merge_step,
)
from orchestrator.runtime.state import CHECKPOINT_SERDE_MODULES, GraphState, RunContext, RunStatus

_SERDE = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_SERDE_MODULES)


class DeterministicScheduler:
    def __init__(
        self,
        workspace: Workspace,
        adapter: HarnessAdapter | HarnessRegistry,
        repo: Path,
        *,
        checkpoint_db: Path | None = None,
        bus: MessageBus | None = None,
        agent: OrchestratorAgent | None = None,
    ) -> None:
        self.workspace = workspace
        # Accept a bare adapter (pre-M6a call style) or a registry; normalize to
        # a registry so per-role.harness resolution is uniform.
        self.registry = (
            adapter if isinstance(adapter, HarnessRegistry) else HarnessRegistry.single(adapter)
        )
        self.repo = Path(repo)
        self.checkpoint_db = (
            Path(checkpoint_db)
            if checkpoint_db is not None
            else self.repo / ".orch" / "checkpoints.sqlite"
        )
        # Same-process convenience: caches dynamically-constructed pipelines so that
        # resume() can find them within the same process. Cross-process resume requires
        # the pipeline to be defined in the workspace (workspace.pipelines[pipeline_name]).
        self._pipeline_cache: dict[str, Pipeline] = {}
        self.bus = bus or MessageBus()
        self.agent = agent or OrchestratorAgent(
            workspace=workspace, registry=self.registry, bus=self.bus, repo=self.repo
        )

    def _make_node(self, pipeline: Pipeline, step: Step):
        async def node(state: GraphState) -> dict:
            ctx = state["ctx"]
            if step.type == StepType.task:
                if step.merge_strategy is not None:
                    adapter = self.registry.default_adapter()
                    await run_merge_step(
                        self.workspace, pipeline, step, ctx, repo=self.repo, adapter=adapter
                    )
                else:
                    await self.agent.run_task(pipeline, step, ctx)
            elif step.type == StepType.agent:
                harness = self.workspace.roles[step.role].harness
                adapter = self.registry.adapter_for(harness)
                await run_agent_step(
                    self.workspace, pipeline, step, ctx,
                    repo=self.repo, adapter=adapter, agent=self.agent,
                )
            else:  # gate
                run_gate_step(step, ctx)
            return {"ctx": ctx}

        return node

    def _router(self, pipeline: Pipeline):
        by_id = {s.id: s for s in pipeline.steps}

        def router(source: str, targets: list[str]):
            src = by_id[source]
            reject_target = src.on_reject
            forward = [t for t in targets if t != reject_target]

            def route_fn(state: GraphState) -> str:
                ctx = state["ctx"]
                if src.type == StepType.gate:
                    if ctx.gate_decisions.get(source) == "reject":
                        return END
                    return forward[0] if forward else END
                art = ctx.artifacts.get(source)
                verdict = (art.output_data or {}).get("verdict") if art else None
                if (
                    verdict == Verdict.REJECT
                    and reject_target is not None
                    and ctx.attempts.get(reject_target, 0) <= by_id[reject_target].max_retries
                ):
                    # `verdict == REJECT` was read from art.output_data, so art is non-None here.
                    self.agent.relay_verdict(art.output, to_step=reject_target, ctx=ctx)
                    return reject_target
                return forward[0] if forward else END

            return route_fn

        return router

    @asynccontextmanager
    async def _saver(self):
        self.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_db)) as saver:
            saver.serde = _SERDE
            yield saver

    def _build(self, pipeline: Pipeline, saver):
        ir = build_ir(pipeline)
        by_id = {s.id: s for s in pipeline.steps}
        builder = StateGraph(GraphState)
        for node_id in ir.nodes:
            builder.add_node(node_id, self._make_node(pipeline, by_id[node_id]))
        wire_edges(builder, ir, router=self._router(pipeline))
        return builder.compile(checkpointer=saver)

    def _finalize(self, result: dict) -> RunContext:
        ctx = result["ctx"]
        interrupts = result.get("__interrupt__")
        if interrupts:
            ctx.status = RunStatus.PAUSED
            ctx.pending_interrupt = dict(interrupts[0].value)
        elif ctx.status == RunStatus.RUNNING:
            ctx.status = RunStatus.COMPLETED
        return ctx

    async def run(
        self, pipeline: Pipeline, inputs: dict[str, str], run_id: str
    ) -> RunContext:
        self._pipeline_cache[pipeline.name] = pipeline
        ctx = RunContext(run_id=run_id, inputs=dict(inputs), pipeline_name=pipeline.name)
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
        tracer = get_tracer()
        async with self._saver() as saver:
            graph = self._build(pipeline, saver)
            with tracer.start_as_current_span(SPAN_RUN) as run_span:
                run_span.set_attribute("run.id", run_id)
                run_span.set_attribute("pipeline", pipeline.name)
                result = await graph.ainvoke({"ctx": ctx}, config)
        return self._finalize(result)

    async def resume(self, run_id: str, decision: str) -> RunContext:
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
        async with self._saver() as saver:
            ckpt = await saver.aget(config)
            if ckpt is None:
                raise KeyError(f"no checkpoint for run '{run_id}'")
            ctx_pre = ckpt["channel_values"]["ctx"]
            pipeline_name = ctx_pre.pipeline_name
            pipeline = (
                self._pipeline_cache.get(pipeline_name) or self.workspace.pipelines[pipeline_name]
            )
            graph = self._build(pipeline, saver)
            result = await graph.ainvoke(Command(resume=decision), config)
            return self._finalize(result)
