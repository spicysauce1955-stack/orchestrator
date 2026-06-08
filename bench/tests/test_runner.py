import subprocess
from pathlib import Path

from bench.runner import grade, make_repo_copy

BENCH = Path(__file__).resolve().parents[1]


def _commit_solution(repo: Path, src: Path) -> None:
    (repo / "ttl_cache.py").write_text(src.read_text())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "solve"], cwd=repo, check=True, capture_output=True)


def test_reference_solution_grades_as_pass(tmp_path):
    repo = make_repo_copy("fake-good", dest_root=tmp_path)
    _commit_solution(repo, BENCH / "reference" / "ttl_cache.py")
    result = grade(repo, hidden_dir=BENCH / "tests_hidden")
    assert result.passed is True
    assert result.failed == 0


def test_stub_grades_as_fail(tmp_path):
    repo = make_repo_copy("fake-bad", dest_root=tmp_path)  # stub left in place
    result = grade(repo, hidden_dir=BENCH / "tests_hidden")
    assert result.passed is False
    assert result.failed > 0


def test_run_contestant_with_injected_agent_grades(tmp_path):
    # A fake "agent" that writes the reference solution; proves the run→grade
    # pipeline works end-to-end with zero model spend.
    from bench.runner import run_contestant

    def fake_agent(repo: Path) -> str:
        (repo / "ttl_cache.py").write_text((BENCH / "reference" / "ttl_cache.py").read_text())
        return (
            '{"type":"result","total_cost_usd":0.01,"num_turns":3,'
            '"usage":{"input_tokens":10,"output_tokens":5}}'
        )

    outcome = run_contestant("fake", fake_agent, dest_root=tmp_path,
                             hidden_dir=BENCH / "tests_hidden")
    assert outcome.grade.passed is True
    assert outcome.wall_s >= 0
