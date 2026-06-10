import os
import subprocess
import sys
from pathlib import Path

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
PLAN = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts" / "plan.ndjson"
SCRIPTS_DIR = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"


def test_fake_harness_streams_script_and_records_argv(tmp_path):
    argv_file = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "ORCH_FAKE_ARGV": str(argv_file),
        "ORCH_FAKE_SCRIPT": str(PLAN),
    }
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "hello", "--output-format", "stream-json"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    # argv recorded
    recorded = argv_file.read_text().splitlines()
    assert "-p" in recorded
    assert "--output-format" in recorded
    # NDJSON streamed: first line is system/init, last is result
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert '"type": "system"' in lines[0] or '"type":"system"' in lines[0]
    assert '"type": "result"' in lines[-1] or '"type":"result"' in lines[-1]


def test_script_dir_routes_classify_by_prompt_keyword(tmp_path):
    env = {
        **os.environ,
        "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR),
    }
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "Classify this task as ...",
         "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    assert '"kind"' in last  # classify.ndjson result carries a kind field


def test_script_dir_falls_back_to_default(tmp_path):
    env = {**os.environ, "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR)}
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "Write a plan", "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    assert '"type": "result"' in last or '"type":"result"' in last
    assert '"kind"' not in last  # default.ndjson is plain text


def test_fake_delete_removes_file(tmp_path, monkeypatch):
    import os

    victim = tmp_path / "doomed.txt"
    victim.write_text("x")
    env = {**os.environ, "ORCH_FAKE_SCRIPT": str(PLAN), "ORCH_FAKE_DELETE": str(victim)}
    subprocess.run(
        [sys.executable, str(FAKE), "-p", "hi", "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    assert not victim.exists()


def test_state_selects_numbered_review_variant(tmp_path, monkeypatch):
    import os

    state = tmp_path / "state.json"
    env = {
        **os.environ,
        "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR),
        "ORCH_FAKE_STATE": str(state),
    }

    def run():
        return subprocess.run(
            [sys.executable, str(FAKE), "-p", "Please review this",
             "--output-format", "stream-json"],
            env=env, capture_output=True, text=True,
        ).stdout

    first = run()   # review.1.ndjson -> reject
    second = run()  # review.2.ndjson -> approve
    assert "reject" in first
    assert "approve" in second


def test_calls_log_appends_per_invocation(tmp_path):
    calls = tmp_path / "calls.log"
    env = {**os.environ, "ORCH_FAKE_SCRIPT": str(PLAN), "ORCH_FAKE_CALLS": str(calls)}
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(FAKE), "-p", "hi", "--output-format", "stream-json"],
            env=env, capture_output=True, text=True,
        )
    assert len(calls.read_text().splitlines()) == 2


def test_winner_keyword_routes_to_judge_script(tmp_path):
    env = {**os.environ, "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR)}
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p",
         'Pick the best candidate. Reply with JSON {"winner": "<k>"}.',
         "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert '\\"winner\\": \\"2\\"' in proc.stdout


def test_implement_keyword_supports_numbered_state_variants(tmp_path):
    """Candidates of a best-of step are distinguished via $ORCH_FAKE_STATE numbering."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for src in ("default.ndjson", "winner.ndjson"):
        (scripts / src).write_text((SCRIPTS_DIR / src).read_text())
    one = (SCRIPTS_DIR / "plan.ndjson").read_text().replace("plan", "cand-one")
    (scripts / "implement.1.ndjson").write_text(one.replace("Here is the", "Candidate one"))
    (scripts / "implement.2.ndjson").write_text(one.replace("Here is the", "Candidate two"))
    state = tmp_path / "state.json"
    env = {**os.environ, "ORCH_FAKE_SCRIPT_DIR": str(scripts), "ORCH_FAKE_STATE": str(state)}

    outs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, str(FAKE), "-p", "Implement the feature",
             "--output-format", "stream-json"],
            env=env, capture_output=True, text=True,
        )
        assert proc.returncode == 0
        outs.append(proc.stdout)
    assert "Candidate one" in outs[0]
    assert "Candidate two" in outs[1]


def test_implement_keyword_without_scripts_falls_back_to_default(tmp_path):
    env = {**os.environ, "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR)}
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "Implement this plan",
         "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    default = (SCRIPTS_DIR / "default.ndjson").read_text().splitlines()[-1]
    assert default.strip() in proc.stdout
