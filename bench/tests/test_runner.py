import subprocess
from pathlib import Path

import pytest

from bench.runner import grade, hidden_dir, make_repo_copy, run_contestant, task_names

BENCH = Path(__file__).resolve().parents[1]
TASKS = BENCH / "tasks"


def _module_name(task: str) -> str:
    """The single stub module at the template root (tests/ live in a subdir)."""
    return next(p.name for p in (TASKS / task / "template").glob("*.py"))


def _commit_solution(repo: Path, src: Path, module: str) -> None:
    (repo / module).write_text(src.read_text())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "solve"], cwd=repo, check=True, capture_output=True)


@pytest.mark.parametrize("task", task_names())
def test_reference_solution_grades_as_pass(task, tmp_path):
    repo = make_repo_copy(task, "fake-good", dest_root=tmp_path)
    module = _module_name(task)
    _commit_solution(repo, TASKS / task / "reference" / module, module)
    result = grade(repo, hidden_dir=hidden_dir(task))
    assert result.passed is True
    assert result.failed == 0


@pytest.mark.parametrize("task", task_names())
def test_stub_grades_as_fail(task, tmp_path):
    repo = make_repo_copy(task, "fake-bad", dest_root=tmp_path)  # stub left in place
    result = grade(repo, hidden_dir=hidden_dir(task))
    assert result.passed is False
    assert result.failed > 0


def test_run_contestant_with_injected_agent_grades(tmp_path):
    # A fake "agent" that writes the reference solution; proves the run→grade
    # pipeline works end-to-end with zero model spend.
    task = "ttl_cache"
    module = _module_name(task)

    def fake_agent(task_name: str, repo: Path) -> str:
        ref = TASKS / task_name / "reference" / module
        (repo / module).write_text(ref.read_text())
        return (
            '{"type":"result","total_cost_usd":0.01,"num_turns":3,'
            '"usage":{"input_tokens":10,"output_tokens":5}}'
        )

    outcome = run_contestant(task, "fake", fake_agent, dest_root=tmp_path,
                             hidden_dir=hidden_dir(task))
    assert outcome.grade.passed is True
    assert outcome.wall_s >= 0
