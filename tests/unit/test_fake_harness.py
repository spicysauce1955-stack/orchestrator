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


def test_calls_log_appends_per_invocation(tmp_path):
    calls = tmp_path / "calls.log"
    env = {**os.environ, "ORCH_FAKE_SCRIPT": str(PLAN), "ORCH_FAKE_CALLS": str(calls)}
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(FAKE), "-p", "hi", "--output-format", "stream-json"],
            env=env, capture_output=True, text=True,
        )
    assert len(calls.read_text().splitlines()) == 2
