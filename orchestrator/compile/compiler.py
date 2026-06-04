"""Compile a pipeline to a validated IR + LangGraph StateGraph (spec §6).

M1 lowers to LangGraph with placeholder node functions (no execution). This proves
the typed-pipeline + on_reject cycle map cleanly onto StateGraph (open question #13).
Real step executors arrive in M3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from orchestrator.compile.ir import GraphIR, build_ir
from orchestrator.compile.validate import (
    validate_dag,
    validate_file_scope,
    validate_typed_io,
)
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline


@dataclass
class CompileResult:
    pipeline: str
    ir: GraphIR | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class RunState(TypedDict, total=False):
    """Placeholder run state for M1 lowering; expanded with artifacts/cost in M3."""

    status: str


def _placeholder_node(state: RunState) -> dict:
    # M1: nodes do nothing. Executors are wired in M3.
    return {}


def wire_edges(builder, ir: GraphIR, *, router=None) -> None:
    """Wire START/END + step edges onto `builder` from the IR.

    Conditional sources get a single router over their targets. `router` is a
    callable (source, targets) -> routing-fn; if None, a forward-only router
    (always the first target) is used. M4 supplies a verdict-aware router.
    """
    for entry in ir.entrypoints:
        builder.add_edge(START, entry)
    for terminal in ir.terminals:
        builder.add_edge(terminal, END)

    outgoing: dict[str, list] = {}
    for edge in ir.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    for source, edges in outgoing.items():
        if any(e.conditional for e in edges):
            targets = [e.target for e in edges]
            if router is not None:
                route_fn = router(source, targets)
            else:
                def route_fn(state, _targets=targets):
                    return _targets[0]
            builder.add_conditional_edges(source, route_fn, targets)
        else:
            for edge in edges:
                builder.add_edge(edge.source, edge.target)


def to_state_graph(pipeline: Pipeline, ir: GraphIR):
    builder = StateGraph(RunState)
    for node in ir.nodes:
        builder.add_node(node, _placeholder_node)
    wire_edges(builder, ir)
    return builder.compile()


def compile_pipeline(workspace: Workspace, pipeline_name: str) -> CompileResult:
    pipeline = workspace.pipelines.get(pipeline_name)
    if pipeline is None:
        available = ", ".join(sorted(workspace.pipelines)) or "(none)"
        return CompileResult(
            pipeline=pipeline_name,
            errors=[f"unknown pipeline '{pipeline_name}'; available: {available}"],
        )

    errors = validate_dag(pipeline)
    if not errors:
        errors = validate_typed_io(pipeline)
    warnings = validate_file_scope(pipeline)

    if errors:
        return CompileResult(pipeline=pipeline_name, errors=errors, warnings=warnings)

    ir = build_ir(pipeline)
    # Prove the graph lowers and compiles; surface any LangGraph friction as an error.
    try:
        to_state_graph(pipeline, ir)
    except Exception as exc:  # pragma: no cover - guards open question #13
        return CompileResult(
            pipeline=pipeline_name,
            ir=ir,
            errors=[f"LangGraph lowering failed: {exc}"],
            warnings=warnings,
        )

    return CompileResult(pipeline=pipeline_name, ir=ir, warnings=warnings)
