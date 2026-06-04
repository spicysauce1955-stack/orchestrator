from orchestrator.compile.ir import Edge, build_ir
from orchestrator.config.schemas import Pipeline


def _pipeline() -> Pipeline:
    return Pipeline.model_validate(
        {
            "steps": [
                {"id": "classify", "type": "task", "prompt": "Classify <task>"},
                {"id": "plan", "role": "planner", "needs": ["classify"]},
                {"id": "implement", "role": "implementer", "needs": ["plan"], "max_retries": 2},
                {"id": "review", "role": "reviewer", "needs": ["implement"], "on_reject": "implement"},
                {"id": "test", "role": "implementer", "needs": ["review"]},
            ]
        }
    )


def test_nodes_match_step_ids():
    ir = build_ir(_pipeline())
    assert ir.nodes == ["classify", "plan", "implement", "review", "test"]


def test_needs_become_edges():
    ir = build_ir(_pipeline())
    assert Edge("classify", "plan") in ir.edges
    assert Edge("plan", "implement") in ir.edges
    assert Edge("implement", "review") in ir.edges


def test_on_reject_is_a_conditional_back_edge():
    ir = build_ir(_pipeline())
    assert Edge("review", "implement", conditional=True) in ir.edges
    # review's forward edge becomes conditional too (router chooses reject vs forward)
    assert Edge("review", "test", conditional=True) in ir.edges


def test_entrypoints_and_terminals():
    ir = build_ir(_pipeline())
    assert ir.entrypoints == ["classify"]
    assert ir.terminals == ["test"]
