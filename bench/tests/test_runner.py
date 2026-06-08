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
