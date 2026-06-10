"""best-of-n executor (spec §4, M9): N candidates -> read-only judge selects.

Fake-harness driven: candidate prompts route to numbered `implement.<n>` scripts
(distinct outputs); the judge prompt asks for {"winner": ...} and routes to a
winner script. No silent fallback: a failed/unparseable judge is a step error.
"""

import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.executors import run_best_of_step
from orchestrator.runtime.state import RunContext
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _cand_script(n: int, text: str, *, is_error: bool = False) -> str:
    err = "true" if is_error else "false"
    return (
        f'{{"type":"system","subtype":"init","session_id":"cand-{n}","tools":[],"cwd":"."}}\n'
        f'{{"type":"assistant","message":{{"content":[{{"type":"text","text":"{text}"}}]}}}}\n'
        f'{{"type":"result","subtype":"success","is_error":{err},"result":"{text}",'
        f'"total_cost_usd":0.01,"usage":{{"input_tokens":10,"output_tokens":5}},'
        f'"session_id":"cand-{n}"}}\n'
    )


def _scripts_dir(tmp_path: Path, *, cand1_error: bool = False, cand2_error: bool = False,
                 judge_prose: bool = False) -> Path:
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "default.ndjson").write_text((SCRIPTS / "default.ndjson").read_text())
    (d / "implement.1.ndjson").write_text(
        _cand_script(1, "Candidate one implementation.", is_error=cand1_error)
    )
    (d / "implement.2.ndjson").write_text(
        _cand_script(2, "Candidate two implementation.", is_error=cand2_error)
    )
    if judge_prose:
        (d / "winner.ndjson").write_text(
            _cand_script(9, "Both look fine to me, hard to say.")
        )
    else:
        (d / "winner.ndjson").write_text((SCRIPTS / "winner.ndjson").read_text())
    return d


def _step() -> Step:
    return Step(
        id="implement", role="implementer", prompt="Implement the feature",
        best_of=2, judge="reviewer",
    )


def _pipeline(step: Step) -> Pipeline:
    return Pipeline(name="bo", inputs={"task": "string"}, steps=[step])


async def _run(tmp_path, monkeypatch, **scripts_kw):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(_scripts_dir(tmp_path, **scripts_kw)))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("ORCH_FAKE_CALLS", str(calls))
    configure_tracing(exporter=InMemorySpanExporter())
    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    step = _step()
    ctx = RunContext(run_id="bo1", inputs={"task": "x"})
    final = await run_best_of_step(
        ws, _pipeline(step), step, ctx,
        repo=repo, adapter=adapter, judge_adapter=adapter,
    )
    return final, ctx, calls


async def test_judge_selects_winner(tmp_path, monkeypatch):
    final, ctx, _ = await _run(tmp_path, monkeypatch)

    assert final.step_id == "implement"
    assert final.is_error is False
    assert final.output_data["winner"] == "2"
    assert "Candidate two" in final.output
    assert final.diff.strip()  # winner's diff carried for downstream merge
    for key in ("implement.cand1", "implement.cand2", "implement.judge", "implement"):
        assert key in ctx.artifacts
    # candidates 0.01 + 0.01 + judge 0.004, summed on the final artifact but
    # NOT double-counted into the run total.
    assert abs(final.cost_usd - 0.024) < 1e-9
    assert abs(ctx.total_cost_usd - 0.024) < 1e-9


async def test_unparseable_judge_is_an_error_not_a_fallback(tmp_path, monkeypatch):
    final, ctx, _ = await _run(tmp_path, monkeypatch, judge_prose=True)

    assert final.is_error is True
    assert "judge" in final.output.lower()


async def test_all_candidates_failing_skips_judge(tmp_path, monkeypatch):
    final, ctx, calls = await _run(
        tmp_path, monkeypatch, cand1_error=True, cand2_error=True
    )

    assert final.is_error is True
    assert "judge" not in calls.read_text().lower()  # judge never driven


async def test_single_qualifier_wins_without_judge(tmp_path, monkeypatch):
    final, ctx, calls = await _run(tmp_path, monkeypatch, cand1_error=True)

    assert final.is_error is False
    assert final.output_data["winner"] == "2"
    assert "Candidate two" in final.output
    assert "judge" not in calls.read_text().lower()


async def test_scheduler_runs_best_of_pipeline_through_merge(tmp_path, monkeypatch):
    """E2E: classify-free pipeline implement(best_of)->merge; winner diff lands."""
    from orchestrator.runtime.scheduler import DeterministicScheduler
    from orchestrator.runtime.state import RunStatus

    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(_scripts_dir(tmp_path)))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")
    configure_tracing(exporter=InMemorySpanExporter())
    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    pipeline = Pipeline.model_validate({
        "name": "bo-e2e",
        "inputs": {"task": "string"},
        "steps": [
            {"id": "implement", "role": "implementer", "prompt": "Implement the feature",
             "best_of": 2, "judge": "reviewer"},
            {"id": "merge", "type": "task", "needs": ["implement"],
             "merge_strategy": "sequential-rebase"},
        ],
    })
    scheduler = DeterministicScheduler(ws, adapter, repo)

    ctx = await scheduler.run(pipeline, {"task": "x"}, run_id="boe2e")

    assert ctx.status == RunStatus.COMPLETED
    assert ctx.artifacts["implement"].output_data["winner"] == "2"
    merge_art = ctx.artifacts["merge"]
    assert merge_art.is_error is False, merge_art.output
