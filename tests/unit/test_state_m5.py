from orchestrator.runtime.state import CHECKPOINT_SERDE_MODULES, RunContext, RunStatus


def test_runcontext_m5_defaults():
    ctx = RunContext(run_id="r1")
    assert ctx.status == RunStatus.RUNNING
    assert ctx.pipeline_name == ""
    assert ctx.gate_decisions == {}
    assert ctx.pending_interrupt is None


def test_runcontext_records_gate_decision():
    ctx = RunContext(run_id="r1")
    ctx.gate_decisions["approve"] = "approve"
    assert ctx.gate_decisions["approve"] == "approve"


def test_serde_modules_cover_state_types():
    assert ("orchestrator.runtime.state", "RunContext") in CHECKPOINT_SERDE_MODULES
    assert ("orchestrator.runtime.state", "Artifact") in CHECKPOINT_SERDE_MODULES
