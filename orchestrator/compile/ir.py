"""Deterministic graph IR derived from a pipeline (spec §6 "Compile")."""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.config.schemas import Pipeline


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    conditional: bool = False


@dataclass
class GraphIR:
    nodes: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    terminals: list[str] = field(default_factory=list)


def build_ir(pipeline: Pipeline) -> GraphIR:
    steps = pipeline.steps
    by_id = {s.id: s for s in steps}

    # A step that declares on_reject is a branch point: ALL of its outgoing edges
    # (forward successors + the reject back-edge) are conditional.
    reject_sources = {s.id for s in steps if s.on_reject}

    # Order matters: emit forward (`needs`) edges BEFORE `on_reject` back-edges.
    # The compiler's forward-only router (wire_edges) picks targets[0], so the
    # forward successor must come first to keep the M3 graph acyclic.
    raw: list[Edge] = []
    for s in steps:
        for dep in s.needs:
            raw.append(Edge(dep, s.id))
    for s in steps:
        if s.on_reject:
            raw.append(Edge(s.id, s.on_reject))

    edges = [
        Edge(e.source, e.target, conditional=e.source in reject_sources) for e in raw
    ]

    needed = {dep for s in steps for dep in s.needs}
    entrypoints = [s.id for s in steps if not s.needs]
    terminals = [
        s.id for s in steps if s.id not in needed and not by_id[s.id].on_reject
    ]

    return GraphIR(
        nodes=[s.id for s in steps],
        edges=edges,
        entrypoints=entrypoints,
        terminals=terminals,
    )
