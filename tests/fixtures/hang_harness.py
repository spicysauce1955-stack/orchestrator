#!/usr/bin/env python3
"""Fixture child for stream-abandonment tests: emit one NDJSON line, then hang.

Prints $ORCH_HANG_LINE (a valid first event for whichever adapter spawned us),
records our PID at $ORCH_HANG_PID_FILE, and sleeps far longer than any test
timeout. If the adapter under test cleans up correctly, we die by SIGKILL.
"""

import os
import time

print(os.environ["ORCH_HANG_LINE"], flush=True)
with open(os.environ["ORCH_HANG_PID_FILE"], "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(300)
