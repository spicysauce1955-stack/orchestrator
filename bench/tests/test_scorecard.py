from bench.scorecard import Row, integrity_flags, render_scorecard


def test_integrity_flags_detect_hidden_test_peeking():
    transcript = "let me look at tests_hidden/test_ttl_cache.py to see expectations"
    flags = integrity_flags(transcript, diff="def get(self,k): return 1")
    assert any("hidden" in f.lower() for f in flags)


def test_integrity_flags_clean_transcript_has_none():
    flags = integrity_flags("implementing the LRU logic now", diff="ok")
    assert flags == []


def test_render_scorecard_has_all_contestants_and_axes():
    rows = [
        Row("A orchestrator", passed=True, cost_usd=0.21, wall_s=95.0, turns=12,
            integrity=[], quality="4/5 clear naming"),
        Row("B claude code", passed=True, cost_usd=0.04, wall_s=40.0, turns=7,
            integrity=[], quality="4/5"),
        Row("C codex", passed=False, cost_usd=None, wall_s=60.0, turns=5,
            integrity=["peeked at hidden tests"], quality="2/5 incomplete"),
    ]
    md = render_scorecard(rows, task="TtlCache", verdict="A and B solved it; C did not.")
    assert "A orchestrator" in md and "C codex" in md
    assert "pass@1" in md.lower()
    assert "TtlCache" in md
    assert "peeked at hidden tests" in md
