# Codex adapter follow-ups

Deferred items from the CodexCLIAdapter work (2026-06-10), flagged in review.

- **`_stream` abandonment orphans the subprocess (all 3 adapters).** If the
  consumer abandons the event stream mid-iteration (task cancellation /
  exception in the executor loop), `GeneratorExit` is thrown at the `yield`:
  `proc.wait()` and the stderr-drain task are never awaited, leaving the child
  running and an un-awaited asyncio Task. Identical exposure in
  `claude_code.py`, `opencode.py`, and `codex.py` (pattern was inherited, not
  introduced). Fix is mechanical and shared: wrap the stream loop in
  `try/except GeneratorExit: proc.kill(); await proc.wait(); stderr_task.cancel(); raise`
  in all three `_stream` methods, with a mid-stream-break test each. Best done
  as one cross-cutting commit, not per-adapter.
- **`cancel()` does not kill a running subprocess** (same as siblings). Benign
  today: the executor only cancels after the stream is fully consumed. Becomes
  relevant if a timeout/budget kill path ever calls `cancel()` mid-prompt —
  fold into the same cross-cutting fix.
- **Codex USD cost is always 0.0.** `codex exec --json` reports tokens but no
  price; deriving cost needs an external price table (same gap as the bench's
  `parse_codex_jsonl`, which leaves cost `None`).
- **Codex-native session resume/fork not wired.** `resume()` returns the
  handle unchanged (MVP stance shared by all adapters); codex's `resume`/
  `fork` subcommands could give it real continuation later.
