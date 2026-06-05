"""DeterministicScheduler: the declarative Controller (spec §6).

Builds an executable LangGraph StateGraph from the pipeline IR with real node
closures and invokes it. A single shared RunContext is threaded through nodes.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from orchestrator.compile.compiler import wire_edges
from orchestrator.compile.ir import build_ir
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.eval.verdict import Verdict
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.observability.spans import SPAN_RUN, get_tracer
from orchestrator.runtime.executors import run_agent_step, run_task_step
from orchestrator.runtime.state import GraphState, RunContext


class DeterministicScheduler:
    def __init__(self, workspace: Workspace, adapter: HarnessAdapter, repo: Path) -> None:
        self.workspace = workspace
        self.adapter = adapter
        self.repo = Path(repo)

    def _make_node(self, pipeline: Pipeline, step: Step):
        async def node(state: GraphState) -> dict:
            ctx = state["ctx"]
            if step.type == StepType.task:
                await run_task_step(
                    self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self.adapter
                )
            elif step.type == StepType.agent:
                await run_agent_step(
                    self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self.adapter
                )
            else:  # gate
                raise NotImplementedError(f"gate step '{step.id}' runs in M5")
            return {"ctx": ctx}

        return node

    def _verdict_router(self, pipeline: Pipeline):
        by_id = {s.id: s for s in pipeline.steps}

        def router(source: str, targets: list[str]):
            reject_target = by_id[source].on_reject
            forward = [t for t in targets if t != reject_target]

            def route_fn(state: GraphState) -> str:
                ctx = state["ctx"]
                art = ctx.artifacts.get(source)
                verdict = (art.output_data or {}).get("verdict") if art else None
                if (
                    verdict == Verdict.REJECT
                    and reject_target is not None
                    and ctx.attempts.get(reject_target, 0) <= by_id[reject_target].max_retries
                ):
                    return reject_target
                return forward[0] if forward else END

            return route_fn

        return router

    def _build(self, pipeline: Pipeline):
        ir = build_ir(pipeline)
        by_id = {s.id: s for s in pipeline.steps}
        builder = StateGraph(GraphState)
        for node_id in ir.nodes:
            builder.add_node(node_id, self._make_node(pipeline, by_id[node_id]))
        wire_edges(builder, ir, router=self._verdict_router(pipeline))
        return builder.compile()

    async def run(
        self, pipeline: Pipeline, inputs: dict[str, str], run_id: str
    ) -> RunContext:
        ctx = RunContext(run_id=run_id, inputs=dict(inputs))
        graph = self._build(pipeline)
        tracer = get_tracer()
        with tracer.start_as_current_span(SPAN_RUN) as run_span:
            run_span.set_attribute("run.id", run_id)
            run_span.set_attribute("pipeline", pipeline.name)
            await graph.ainvoke({"ctx": ctx}, {"recursion_limit": 100})
        return ctx
