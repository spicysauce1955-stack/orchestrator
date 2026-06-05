"""Evaluation layer: verdicts + success criteria + test-count gate (spec §6, §9)."""

from orchestrator.eval.criteria import (
    count_tests,
    run_success_criteria,
    test_count_regressed,
)
from orchestrator.eval.verdict import Verdict, parse_output

__all__ = [
    "parse_output",
    "Verdict",
    "run_success_criteria",
    "count_tests",
    "test_count_regressed",
]
