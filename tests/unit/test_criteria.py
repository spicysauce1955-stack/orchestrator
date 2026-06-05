import subprocess

from orchestrator.eval.criteria import (
    count_tests,
    run_success_criteria,
)
from orchestrator.eval.criteria import (
    test_count_regressed as check_test_count_regressed,
)


def test_run_success_criteria_ok(tmp_path):
    ok, out = run_success_criteria("echo hi && true", tmp_path)
    assert ok is True
    assert "hi" in out


def test_run_success_criteria_fail(tmp_path):
    ok, out = run_success_criteria("echo boom >&2; false", tmp_path)
    assert ok is False
    assert "boom" in out


def test_count_tests_counts_functions(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_one():\n    assert True\n\nasync def test_two():\n    assert True\n"
    )
    (tmp_path / "tests" / "helpers_b.py").write_text("def not_a_test():\n    pass\n")
    assert count_tests(tmp_path) == 2


def test_count_tests_ignores_git_dir(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "test_x.py").write_text("def test_x():\n    pass\n")
    assert count_tests(tmp_path) == 1


def test_test_count_regressed():
    assert check_test_count_regressed(3, 2) is True
    assert check_test_count_regressed(2, 2) is False
    assert check_test_count_regressed(2, 5) is False
