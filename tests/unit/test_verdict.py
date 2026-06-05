from orchestrator.eval.verdict import Verdict, parse_output


def test_no_schema_returns_none():
    assert parse_output("anything", None) == (None, False)


def test_enum_field_from_json():
    data, err = parse_output('{"kind": "feature"}', {"kind": "enum[bugfix,feature,refactor]"})
    assert data == {"kind": "feature"} and err is False


def test_enum_bare_value_single_field():
    data, err = parse_output("approve", {"verdict": "enum[approve,reject]"})
    assert data == {"verdict": "approve"} and err is False


def test_enum_invalid_value_is_error():
    data, err = parse_output('{"verdict": "maybe"}', {"verdict": "enum[approve,reject]"})
    assert data is None and err is True


def test_verdict_constants():
    assert Verdict.APPROVE == "approve"
    assert Verdict.REJECT == "reject"
