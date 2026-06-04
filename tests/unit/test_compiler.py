from orchestrator.compile.compiler import CompileResult, compile_pipeline, to_state_graph
from orchestrator.compile.ir import build_ir
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Pipeline, Role


def _workspace() -> Workspace:
    pipeline = Pipeline.model_validate(
        {
            "name": "feature",
            "inputs": {"task": "string"},
            "steps": [
                {"id": "classify", "type": "task", "prompt": "Classify <task>"},
                {"id": "plan", "role": "planner", "needs": ["classify"]},
                {"id": "implement", "role": "implementer", "needs": ["plan"], "max_retries": 2},
                {
                    "id": "review",
                    "role": "reviewer",
                    "needs": ["implement"],
                    "on_reject": "implement",
                },
                {"id": "test", "role": "implementer", "needs": ["review"]},
            ],
        }
    )
    roles = {
        name: Role.model_validate({"harness": "claude-code"})
        for name in ("planner", "implementer", "reviewer")
    }
    for name, role in roles.items():
        role.name = name
    return Workspace(config=Config(), roles=roles, pipelines={"feature": pipeline})


def test_compile_ok_pipeline_has_no_errors():
    result = compile_pipeline(_workspace(), "feature")
    assert isinstance(result, CompileResult)
    assert result.ok
    assert result.errors == []


def test_compile_unknown_pipeline_errors():
    result = compile_pipeline(_workspace(), "ghost")
    assert not result.ok
    assert any("ghost" in e for e in result.errors)


def test_golden_graph_node_and_edge_set_is_stable():
    result = compile_pipeline(_workspace(), "feature")
    nodes = set(result.ir.nodes)
    edges = {(e.source, e.target, e.conditional) for e in result.ir.edges}

    assert nodes == {"classify", "plan", "implement", "review", "test"}
    assert edges == {
        ("classify", "plan", False),
        ("plan", "implement", False),
        ("implement", "review", False),
        ("review", "test", True),
        ("review", "implement", True),
    }


def test_lowers_to_compilable_langgraph_state_graph():
    pipeline = _workspace().pipelines["feature"]
    ir = build_ir(pipeline)
    compiled = to_state_graph(pipeline, ir)
    drawn = compiled.get_graph()
    # Every IR node must exist in the LangGraph (plus LangGraph's __start__/__end__).
    assert {"classify", "plan", "implement", "review", "test"} <= set(drawn.nodes)
