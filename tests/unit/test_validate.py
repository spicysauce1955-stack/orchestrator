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


from orchestrator.compile.validate import validate_typed_io


def test_input_reference_resolves():
    p = Pipeline.model_validate(
        {
            "inputs": {"task": "string"},
            "steps": [{"id": "classify", "type": "task", "prompt": "Classify <task>"}],
        }
    )
    assert validate_typed_io(p) == []


def test_unknown_input_reference_reported():
    p = Pipeline.model_validate(
        {
            "inputs": {"task": "string"},
            "steps": [{"id": "classify", "type": "task", "prompt": "Use <goal>"}],
        }
    )
    errors = validate_typed_io(p)
    assert any("goal" in e for e in errors)


def test_step_output_reference_resolves():
    p = Pipeline.model_validate(
        {
            "steps": [
                {
                    "id": "classify",
                    "type": "task",
                    "prompt": "x",
                    "output_schema": {"kind": "enum[bugfix,feature]"},
                },
                {
                    "id": "plan",
                    "type": "task",
                    "prompt": "Plan for <classify.output.kind>",
                    "needs": ["classify"],
                },
            ]
        }
    )
    assert validate_typed_io(p) == []


def test_unknown_step_output_field_reported():
    p = Pipeline.model_validate(
        {
            "steps": [
                {
                    "id": "classify",
                    "type": "task",
                    "prompt": "x",
                    "output_schema": {"kind": "enum[bugfix]"},
                },
                {
                    "id": "plan",
                    "type": "task",
                    "prompt": "Plan <classify.output.missing>",
                    "needs": ["classify"],
                },
            ]
        }
    )
    errors = validate_typed_io(p)
    assert any("missing" in e for e in errors)


def test_reference_to_unknown_step_reported():
    p = Pipeline.model_validate(
        {"steps": [{"id": "a", "type": "task", "prompt": "Use <ghost.output>"}]}
    )
    errors = validate_typed_io(p)
    assert any("ghost" in e for e in errors)
