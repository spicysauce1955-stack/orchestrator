"""Compile-time pipeline validation (spec §6).

Errors block compilation; warnings do not. Three independent checks:
  - validate_dag: dangling needs, undeclared cycles, on_reject targeting.
  - validate_typed_io: prompt reference resolution (Task 8).
  - validate_file_scope: overlapping write scopes on concurrent steps (Task 9).
"""

from __future__ import annotations

from orchestrator.config.schemas import Pipeline


def _ancestors(step_id: str, deps: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(deps.get(step_id, []))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in deps:
            continue
        seen.add(cur)
        stack.extend(deps[cur])
    return seen


def _has_cycle(ids: list[str], deps: dict[str, list[str]]) -> bool:
    # Kahn's algorithm over the needs-only graph (on_reject edges excluded).
    indegree = {i: 0 for i in ids}
    for node in ids:
        for dep in deps[node]:
            if dep in indegree:
                indegree[node] += 1
    queue = [i for i in ids if indegree[i] == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for node in ids:
            if cur in deps[node]:
                indegree[node] -= 1
                if indegree[node] == 0:
                    queue.append(node)
    return visited != len(ids)


def validate_dag(pipeline: Pipeline) -> list[str]:
    errors: list[str] = []
    ids = [s.id for s in pipeline.steps]
    id_set = set(ids)
    deps = {s.id: list(s.needs) for s in pipeline.steps}

    for step in pipeline.steps:
        for dep in step.needs:
            if dep not in id_set:
                errors.append(f"step '{step.id}' needs unknown step '{dep}'")
            if dep == step.id:
                errors.append(f"step '{step.id}' cannot depend on itself")

    # Cycles in the forward (needs-only) graph are undeclared cycles.
    if all(d in id_set for s in pipeline.steps for d in s.needs):
        if _has_cycle(ids, deps):
            errors.append("pipeline has an undeclared cycle in `needs` edges")

    for step in pipeline.steps:
        if step.on_reject is None:
            continue
        if step.on_reject not in id_set:
            errors.append(
                f"step '{step.id}' on_reject targets unknown step '{step.on_reject}'"
            )
        elif step.on_reject not in _ancestors(step.id, deps):
            errors.append(
                f"step '{step.id}' on_reject must point to an upstream step, got "
                f"'{step.on_reject}'"
            )

    return errors
