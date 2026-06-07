#!/usr/bin/env python3
"""Fake `opencode` binary for tests. Zero API cost.

- Records argv (one per line) to $ORCH_OC_ARGV (if set).
- Records the OPENCODE_CONFIG file path to $ORCH_OC_CONFIG_SEEN (if set).
- Streams the NDJSON at $ORCH_OC_SCRIPT (default scripts/default.ndjson) to stdout.
- If $ORCH_OC_TOUCH is set, creates that file in --dir (or cwd) before finishing.
- Exits 0 unless $ORCH_OC_EXIT is set non-zero.
"""

import os
import sys
from pathlib import Path

DEFAULT_SCRIPT = Path(__file__).parent / "scripts" / "default.ndjson"


def main() -> int:
    args = sys.argv[1:]
    argv_file = os.environ.get("ORCH_OC_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(args))

    cfg_seen = os.environ.get("ORCH_OC_CONFIG_SEEN")
    if cfg_seen:
        Path(cfg_seen).write_text(os.environ.get("OPENCODE_CONFIG", ""))

    # working dir: the value after --dir, else cwd
    workdir = Path(".")
    if "--dir" in args:
        i = args.index("--dir")
        if i + 1 < len(args):
            workdir = Path(args[i + 1])

    touch = os.environ.get("ORCH_OC_TOUCH")
    if touch:
        (workdir / touch).write_text("created by fake opencode\n")

    script = Path(os.environ.get("ORCH_OC_SCRIPT", str(DEFAULT_SCRIPT)))
    sys.stdout.write(script.read_text())
    sys.stdout.flush()
    return int(os.environ.get("ORCH_OC_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
