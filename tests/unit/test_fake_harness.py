import os
import subprocess
import sys
from pathlib import Path

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
PLAN = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts" / "plan.ndjson"


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
