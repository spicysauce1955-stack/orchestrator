#!/usr/bin/env python3
"""Fake `gh` for tests. Records argv to $ORCH_GH_ARGV (if set), prints a PR URL."""
import os
import sys
from pathlib import Path


def main() -> int:
    argv_file = os.environ.get("ORCH_GH_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(sys.argv[1:]))
    if len(sys.argv) >= 3 and sys.argv[1] == "pr" and sys.argv[2] == "create":
        print("https://github.com/example/repo/pull/1")
    return int(os.environ.get("ORCH_GH_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
