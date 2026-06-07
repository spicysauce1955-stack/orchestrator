from pathlib import Path

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import load_workspace

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def test_example_workspace_loads():
    ws = load_workspace(EXAMPLE)
    assert set(ws.roles) == {
        "implementer", "reviewer", "planner", "auditor", "opencoder", "orchestrator"
    }
    assert "test-runner" in ws.skills
    assert ws.core_knowledge.inject  # non-empty
    assert "feature" in ws.pipelines


def test_example_feature_pipeline_compiles():
    ws = load_workspace(EXAMPLE)
    result = compile_pipeline(ws, "feature")
    assert result.ok, result.errors
    assert set(result.ir.nodes) == {
        "classify",
        "plan",
        "implement",
        "review",
        "test",
        "audit",
        "approve",
        "merge",
    }


def test_example_review_loop_is_conditional():
    ws = load_workspace(EXAMPLE)
    result = compile_pipeline(ws, "feature")
    edges = {(e.source, e.target, e.conditional) for e in result.ir.edges}
    assert ("review", "implement", True) in edges


def test_mixed_harness_pipeline_compiles():
    ws = load_workspace(EXAMPLE)
    result = compile_pipeline(ws, "mixed-harness")
    assert result.ok, result.errors
    assert set(result.ir.nodes) == {"classify", "implement"}
    edges = {(e.source, e.target) for e in result.ir.edges}
    assert ("classify", "implement") in edges


def test_qa_demo_pipeline_compiles():
    ws = load_workspace(EXAMPLE)
    result = compile_pipeline(ws, "qa-demo")
    assert result.ok, result.errors
    assert set(result.ir.nodes) == {"classify", "implement"}
    edges = {(e.source, e.target) for e in result.ir.edges}
    assert ("classify", "implement") in edges
