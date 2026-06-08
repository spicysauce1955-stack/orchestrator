from bench.metrics import parse_claude_stream, parse_codex_jsonl


def test_parse_claude_stream_extracts_cost_and_turns():
    stream = (
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n'
        '{"type":"result","subtype":"success","total_cost_usd":0.0421,'
        '"num_turns":7,"usage":{"input_tokens":1200,"output_tokens":300},"result":"done"}\n'
    )
    m = parse_claude_stream(stream)
    assert m.cost_usd == 0.0421
    assert m.turns == 7
    assert m.tokens == 1500


def test_parse_codex_jsonl_counts_turns_and_tokens_tolerantly():
    stream = (
        '{"type":"item.completed","item":{"item_type":"assistant_message"}}\n'
        '{"type":"item.completed","item":{"item_type":"command_execution"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":2000,"output_tokens":500}}\n'
    )
    m = parse_codex_jsonl(stream)
    assert m.turns >= 1
    assert m.tokens == 2500  # summed from any usage objects seen
