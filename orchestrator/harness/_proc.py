"""Shared subprocess cleanup for the CLI adapters (claude_code/opencode/codex)."""

from __future__ import annotations

import asyncio
import contextlib


async def reap(
    proc: asyncio.subprocess.Process,
    stderr_task: asyncio.Task | None = None,
) -> None:
    """Kill + reap `proc` if still running; retire the stderr drain task.

    Safe on every exit path: a no-op when the process already exited and the
    drain task already completed. Awaitable from a GeneratorExit unwind
    (aclose() drives the generator through it; we never yield here).
    """
    if proc.returncode is None:
        proc.kill()
        await proc.wait()
    if stderr_task is not None and not stderr_task.done():
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task
