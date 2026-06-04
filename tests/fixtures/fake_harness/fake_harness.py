#!/usr/bin/env python3
"""Fake coding-agent harness for tests. Zero API cost.

Behavior:
- Records the argv it received (one arg per line) to $ORCH_FAKE_ARGV (if set).
- Streams the NDJSON file at $ORCH_FAKE_SCRIPT to stdout (default: plan.ndjson).
- If $ORCH_FAKE_TOUCH is set, creates that file in the CWD before emitting the
  result (simulates a harness writing a file, so diff capture has something to see).
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

    touch = os.environ.get("ORCH_FAKE_TOUCH")
    if touch:
        Path(touch).write_text("created by fake harness\n")

    script = Path(os.environ.get("ORCH_FAKE_SCRIPT", str(DEFAULT_SCRIPT)))
    for line in script.read_text().splitlines():
        if not line.strip():
            continue
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        time.sleep(0)  # yield, keep streaming semantics

    return int(os.environ.get("ORCH_FAKE_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
