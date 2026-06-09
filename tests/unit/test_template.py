import pytest

from orchestrator.runtime.state import Artifact
from orchestrator.runtime.template import TemplateError, render_template


def _arts():
    return {
        "plan": Artifact("plan", "THE PLAN", "THE DIFF", "b", 0.0, 0, False),
        "classify": Artifact(
            "classify", '{"kind":"feature"}', "", "b", 0.0, 0, False,
            output_data={"kind": "feature"},
        ),
    }


def test_input_substitution():
    assert render_template("Do {{task}} now", {"task": "X"}, {}) == "Do X now"


def test_whitespace_inside_braces():
    assert render_template("Do {{ task }} now", {"task": "X"}, {}) == "Do X now"


def test_step_output_substitution():
    out = render_template("Plan:\n{{plan.output}}", {}, _arts())
    assert out == "Plan:\nTHE PLAN"


def test_step_output_field_substitution():
    out = render_template("Kind={{classify.output.kind}}", {}, _arts())
    assert out == "Kind=feature"


def test_prose_angle_brackets_untouched():
    s = "refactor the List<T> wrapper"
    assert render_template(s, {"task": "x"}, {}) == s


def test_unknown_input_raises():
    with pytest.raises(TemplateError):
        render_template("{{nope}}", {"task": "x"}, {})


def test_unknown_step_raises():
    with pytest.raises(TemplateError):
        render_template("{{ghost.output}}", {}, _arts())


def test_step_diff_substitution():
    out = render_template("Changes:\n{{plan.diff}}", {}, _arts())
    assert out == "Changes:\nTHE DIFF"


def test_diff_with_field_raises():
    with pytest.raises(TemplateError):
        render_template("{{plan.diff.x}}", {}, _arts())


def test_non_output_segment_raises():
    with pytest.raises(TemplateError):
        render_template("{{plan.bogus}}", {}, _arts())


def test_missing_field_raises():
    with pytest.raises(TemplateError):
        render_template("{{classify.output.missing}}", {}, _arts())


def test_deep_field_ref_raises():
    with pytest.raises(TemplateError):
        render_template("{{classify.output.a.b}}", {}, _arts())
