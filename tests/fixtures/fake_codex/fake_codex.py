#!/usr/bin/env python3
"""Fake `codex` binary for tests. Zero API cost.

- Records argv (one per line) to $ORCH_CODEX_ARGV (if set).
- Streams the NDJSON at $ORCH_CODEX_SCRIPT (default scripts/default.ndjson) to stdout.
- If $ORCH_CODEX_TOUCH is set, creates that file under the `-C` dir (or cwd).
- If $ORCH_CODEX_STDERR is set, writes it to stderr.
- Exits 0 unless $ORCH_CODEX_EXIT is set non-zero.
"""

import os
import sys
from pathlib import Path

DEFAULT_SCRIPT = Path(__file__).parent / "scripts" / "default.ndjson"


def main() -> int:
    args = sys.argv[1:]
    argv_file = os.environ.get("ORCH_CODEX_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(args))

    workdir = Path(".")
    if "-C" in args:
        i = args.index("-C")
        if i + 1 < len(args):
            workdir = Path(args[i + 1])

    touch = os.environ.get("ORCH_CODEX_TOUCH")
    if touch:
        (workdir / touch).write_text("created by fake codex\n")

    err = os.environ.get("ORCH_CODEX_STDERR")
    if err:
        sys.stderr.write(err)
        sys.stderr.flush()

    script = Path(os.environ.get("ORCH_CODEX_SCRIPT", str(DEFAULT_SCRIPT)))
    sys.stdout.write(script.read_text())
    sys.stdout.flush()
    return int(os.environ.get("ORCH_CODEX_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
