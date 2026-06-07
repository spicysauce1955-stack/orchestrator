"""Shared helpers for integration tests that drive stdio JSON-RPC subprocesses."""

import json


def rpc_send(proc, obj):
    """Write one newline-delimited JSON-RPC message to a subprocess's stdin."""
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def rpc_read(proc):
    """Read one JSON-RPC reply line; fail clearly if the subprocess produced none."""
    line = proc.stdout.readline()
    assert line.strip(), "subprocess produced no output (did it crash?)"
    return json.loads(line)
