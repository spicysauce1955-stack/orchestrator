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


def test_json_object_embedded_in_prose():
    # Real harnesses wrap the verdict in explanatory prose.
    data, err = parse_output(
        'I reviewed the code and it looks correct.\n\n{"verdict": "approve"}',
        {"verdict": "enum[approve,reject]"},
    )
    assert data == {"verdict": "approve"} and err is False


def test_json_object_in_fenced_code_block():
    data, err = parse_output(
        'Here is my verdict:\n```json\n{"verdict": "reject"}\n```\n',
        {"verdict": "enum[approve,reject]"},
    )
    assert data == {"verdict": "reject"} and err is False


def test_prose_without_parseable_verdict_is_error():
    # No JSON object and the whole text isn't a bare enum value -> error (not a guess).
    data, err = parse_output(
        "The implementation has some issues I'd like to discuss further.",
        {"verdict": "enum[approve,reject]"},
    )
    assert data is None and err is True
