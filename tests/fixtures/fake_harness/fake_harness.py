#!/usr/bin/env python3
"""Fake coding-agent harness for tests. Zero API cost.

Behavior:
- Records the argv it received (one arg per line) to $ORCH_FAKE_ARGV (if set).
- Streams the NDJSON file at $ORCH_FAKE_SCRIPT to stdout (default: plan.ndjson).
- If $ORCH_FAKE_TOUCH is set, creates that file in the CWD before emitting the
  result (simulates a harness writing a file, so diff capture has something to see).
- If $ORCH_FAKE_DELETE is set, deletes that file (relative to CWD) before emitting
  the result (simulates an agent removing tests, to exercise the test-count gate).
- Exits 0 unless $ORCH_FAKE_EXIT is set to a non-zero integer.
"""

import os
import sys
import time
from pathlib import Path

DEFAULT_SCRIPT = Path(__file__).parent / "scripts" / "plan.ndjson"


def main() -> int:
    argv_file = os.environ.get("ORCH_FAKE_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(sys.argv[1:]))

    stderr_bytes = int(os.environ.get("ORCH_FAKE_STDERR_BYTES", "0"))
    if stderr_bytes:
        sys.stderr.write("x" * stderr_bytes)
        sys.stderr.flush()

    # Record the prompt (arg after -p) for routing + logging.
    prompt = ""
    args = sys.argv[1:]
    if "-p" in args:
        i = args.index("-p")
        if i + 1 < len(args):
            prompt = args[i + 1]

    calls_log = os.environ.get("ORCH_FAKE_CALLS")
    if calls_log:
        with open(calls_log, "a") as fh:
            fh.write(prompt[:60] + "\n")

    touch = os.environ.get("ORCH_FAKE_TOUCH")
    if touch:
        Path(touch).write_text("created by fake harness\n")

    delete = os.environ.get("ORCH_FAKE_DELETE")
    if delete:
        p = Path(delete)
        if p.exists():
            p.unlink()

    # Script selection: explicit file wins; else route within a dir by prompt keyword.
    script_env = os.environ.get("ORCH_FAKE_SCRIPT")
    script_dir = os.environ.get("ORCH_FAKE_SCRIPT_DIR")
    if script_env:
        script = Path(script_env)
    elif script_dir:
        name = "classify.ndjson" if "classify" in prompt.lower() else "default.ndjson"
        script = Path(script_dir) / name
    else:
        script = DEFAULT_SCRIPT
    for line in script.read_text().splitlines():
        if not line.strip():
            continue
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        time.sleep(0)  # yield, keep streaming semantics

    return int(os.environ.get("ORCH_FAKE_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
