from orchestrator.compile.validate import validate_dag
from orchestrator.config.schemas import Pipeline


def _p(steps: list[dict]) -> Pipeline:
    return Pipeline.model_validate({"steps": steps})


def test_valid_linear_pipeline_has_no_errors():
    p = _p(
        [
            {"id": "a", "type": "task", "prompt": "x"},
            {"id": "b", "type": "task", "prompt": "y", "needs": ["a"]},
        ]
    )
    assert validate_dag(p) == []


def test_dangling_needs_reported():
    p = _p([{"id": "b", "type": "task", "prompt": "y", "needs": ["a"]}])
    errors = validate_dag(p)
    assert any("unknown step 'a'" in e for e in errors)


def test_undeclared_cycle_in_needs_reported():
    p = _p(
        [
            {"id": "a", "type": "task", "prompt": "x", "needs": ["b"]},
            {"id": "b", "type": "task", "prompt": "y", "needs": ["a"]},
        ]
    )
    errors = validate_dag(p)
    assert any("cycle" in e.lower() for e in errors)


def test_on_reject_back_edge_is_allowed():
    p = _p(
        [
            {"id": "impl", "role": "implementer"},
            {"id": "review", "role": "reviewer", "needs": ["impl"], "on_reject": "impl"},
        ]
    )
    assert validate_dag(p) == []


def test_on_reject_to_unknown_step_reported():
    p = _p(
        [
            {"id": "impl", "role": "implementer"},
            {"id": "review", "role": "reviewer", "needs": ["impl"], "on_reject": "ghost"},
        ]
    )
    errors = validate_dag(p)
    assert any("ghost" in e for e in errors)


def test_on_reject_must_point_upstream():
    p = _p(
        [
            {"id": "a", "role": "x", "on_reject": "b"},
            {"id": "b", "role": "y", "needs": ["a"]},
        ]
    )
    errors = validate_dag(p)
    assert any("upstream" in e.lower() for e in errors)
