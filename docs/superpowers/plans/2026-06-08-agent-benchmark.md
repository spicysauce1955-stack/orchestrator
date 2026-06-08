# Governed-vs-Raw Coding-Agent Benchmark — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible harness that runs one identical, hidden-test-graded coding task (`TtlCache`) through three contestants — the orchestrator's governed pipeline (driving real `claude`), raw `claude code`, and raw `codex` — and emits a four-axis scorecard (pass@1, cost/wall-clock/turns, integrity, quality rubric).

**Architecture:** A self-contained `bench/` tree in the orchestrator repo. A reference `TtlCache` impl is our oracle that validates the held-out grader and powers a zero-cost "fake contestant" for testing the runner plumbing. The runner copies the task into a fresh git repo per contestant, invokes each agent non-interactively with a timer, copies in the held-out tests to grade, scans for integrity flags, and renders `scorecard.md`. Real-agent runs are validated structurally via a fake contestant first; the live 3-way run is the final task.

**Tech Stack:** Python 3.11 + `uv` + pytest; the `orch` CLI (real `claude` binary via `ORCH_CLAUDE_BIN`); `claude -p --output-format stream-json`; `codex exec --json`.

**Spec:** `docs/superpowers/specs/2026-06-08-agent-benchmark-design.md`

---

## File Structure

- `bench/reference/ttl_cache.py` — full reference impl (oracle; NEVER copied to contestants).
- `bench/task_template/ttl_cache.py` — stub agents receive (signatures + `Stats` + `NotImplementedError`).
- `bench/task_template/README.md` — the task description = the prompt.
- `bench/task_template/tests/test_smoke.py` — ~3 visible smoke tests.
- `bench/task_template/pyproject.toml` — makes the copy pytest-runnable.
- `bench/tests_hidden/test_ttl_cache.py` — held-out grader (~12 tests).
- `bench/orchestrator_ws/.orchestrator/{roles,pipelines}/…` — the `bench` pipeline (real claude).
- `bench/runner.py` — experiment orchestrator (repo copy, run A/B/C, metrics, grade, integrity, scorecard).
- `bench/metrics.py` — per-contestant metric parsers (claude/codex/orchestrator).
- `bench/scorecard.py` — scorecard renderer.
- `bench/tests/test_runner.py`, `bench/tests/test_metrics.py`, `bench/tests/test_scorecard.py` — harness unit tests (zero-cost, fake contestant).
- `bench/results/` — gitignored run outputs.

---

## Task 1: Reference impl + held-out grader (prove the task is solvable & graded fairly)

**Files:**
- Create: `bench/task_template/ttl_cache.py`
- Create: `bench/tests_hidden/test_ttl_cache.py`
- Create: `bench/reference/ttl_cache.py`

- [ ] **Step 1: Write the stub** (`bench/task_template/ttl_cache.py`)

```python
"""Bounded in-memory cache: per-key TTL + LRU eviction + stats. (TASK STUB)"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Hashable


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    ttl_evictions: int = 0       # entries removed because they expired
    capacity_evictions: int = 0  # live entries removed to make room for a new key


class TtlCache:
    """See README.md for the full contract."""

    def __init__(self, capacity: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        raise NotImplementedError

    def set(self, key: Hashable, value: Any, *, ttl: float | None = None) -> None:
        raise NotImplementedError

    def get(self, key: Hashable) -> Any | None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    @property
    def stats(self) -> Stats:
        raise NotImplementedError
```

- [ ] **Step 2: Write the held-out grader** (`bench/tests_hidden/test_ttl_cache.py`)

```python
"""Held-out grader for TtlCache. NEVER copied into a contestant's repo."""
from __future__ import annotations

import pytest

from ttl_cache import Stats, TtlCache


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_set_get_roundtrip_and_hit_miss_stats():
    c = TtlCache(capacity=2)
    assert c.get("a") is None          # miss
    c.set("a", 1)
    assert c.get("a") == 1             # hit
    assert c.stats.hits == 1
    assert c.stats.misses == 1


def test_len_counts_live_entries():
    c = TtlCache(capacity=3)
    c.set("a", 1)
    c.set("b", 2)
    assert len(c) == 2


def test_overwrite_updates_value_and_does_not_evict():
    c = TtlCache(capacity=1)
    c.set("a", 1)
    c.set("a", 2)                      # overwrite, must not evict
    assert c.get("a") == 2
    assert len(c) == 1
    assert c.stats.capacity_evictions == 0


def test_capacity_eviction_removes_lru_live_entry():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)                      # evicts LRU "a"
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert c.stats.capacity_evictions == 1


def test_get_refreshes_lru_recency():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1             # "a" now MRU, so "b" is LRU
    c.set("c", 3)                      # evicts "b", not "a"
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.stats.capacity_evictions == 1


def test_set_existing_key_refreshes_recency():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 11)                     # "a" now MRU
    c.set("c", 3)                      # evicts LRU "b"
    assert c.get("a") == 11
    assert c.get("b") is None


def test_ttl_lazy_expiry_on_get_counts_miss_and_ttl_eviction():
    clk = FakeClock()
    c = TtlCache(capacity=2, clock=clk)
    c.set("a", 1, ttl=10)
    clk.advance(10)                    # now expired (>= expiry)
    assert c.get("a") is None
    assert c.stats.misses == 1
    assert c.stats.ttl_evictions == 1
    assert c.stats.hits == 0


def test_ttl_none_never_expires():
    clk = FakeClock()
    c = TtlCache(capacity=2, clock=clk)
    c.set("a", 1)                      # no ttl
    clk.advance(1_000_000)
    assert c.get("a") == 1
    assert c.stats.ttl_evictions == 0


def test_len_purges_expired_and_counts_ttl_eviction():
    clk = FakeClock()
    c = TtlCache(capacity=3, clock=clk)
    c.set("a", 1, ttl=5)
    c.set("b", 2)                      # no ttl
    clk.advance(5)
    assert len(c) == 1                 # "a" purged
    assert c.stats.ttl_evictions == 1


def test_set_purges_expired_before_capacity_eviction():
    clk = FakeClock()
    c = TtlCache(capacity=2, clock=clk)
    c.set("a", 1, ttl=5)
    c.set("b", 2)                      # live, no ttl
    clk.advance(5)                     # "a" expired
    c.set("c", 3)                      # expired "a" purged (ttl), room exists, no capacity evict
    assert c.stats.ttl_evictions == 1
    assert c.stats.capacity_evictions == 0
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_capacity_zero_stores_nothing_and_counts_capacity_eviction():
    c = TtlCache(capacity=0)
    c.set("a", 1)
    assert c.get("a") is None
    assert len(c) == 0
    assert c.stats.capacity_evictions == 1


def test_negative_capacity_raises():
    with pytest.raises(ValueError):
        TtlCache(capacity=-1)
```

- [ ] **Step 3: Run the grader against the STUB — verify it FAILS** (proves the grader discriminates)

Run: `cd bench/task_template && uv run --with pytest pytest -q ../tests_hidden/test_ttl_cache.py`
Expected: FAIL (NotImplementedError across tests).

- [ ] **Step 4: Write the reference impl** (`bench/reference/ttl_cache.py`)

```python
"""Reference TtlCache (oracle). NEVER copied into a contestant's repo."""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Hashable


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    ttl_evictions: int = 0
    capacity_evictions: int = 0


class TtlCache:
    def __init__(self, capacity: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if capacity < 0:
            raise ValueError("capacity must be >= 0")
        self._capacity = capacity
        self._clock = clock
        # key -> (value, expiry_or_None); ordered oldest→newest (LRU at the front)
        self._data: OrderedDict[Hashable, tuple[Any, float | None]] = OrderedDict()
        self._stats = Stats()

    def _is_expired(self, expiry: float | None) -> bool:
        return expiry is not None and self._clock() >= expiry

    def _purge_all_expired(self) -> None:
        for k in [k for k, (_, exp) in self._data.items() if self._is_expired(exp)]:
            del self._data[k]
            self._stats.ttl_evictions += 1

    def get(self, key: Hashable) -> Any | None:
        if key in self._data:
            value, expiry = self._data[key]
            if self._is_expired(expiry):
                del self._data[key]
                self._stats.ttl_evictions += 1
                self._stats.misses += 1
                return None
            self._data.move_to_end(key)
            self._stats.hits += 1
            return value
        self._stats.misses += 1
        return None

    def set(self, key: Hashable, value: Any, *, ttl: float | None = None) -> None:
        expiry = None if ttl is None else self._clock() + ttl
        if key in self._data:                      # overwrite: refresh, never evict
            self._data[key] = (value, expiry)
            self._data.move_to_end(key)
            return
        if self._capacity == 0:
            self._stats.capacity_evictions += 1
            return
        self._purge_all_expired()
        if len(self._data) >= self._capacity:
            oldest = next(iter(self._data))
            del self._data[oldest]
            self._stats.capacity_evictions += 1
        self._data[key] = (value, expiry)
        self._data.move_to_end(key)

    def __len__(self) -> int:
        self._purge_all_expired()
        return len(self._data)

    @property
    def stats(self) -> Stats:
        return self._stats
```

- [ ] **Step 5: Run the grader against the REFERENCE — verify it PASSES** (proves task solvable + grader correct)

Run: `cd bench/reference && uv run --with pytest pytest -q ../tests_hidden/test_ttl_cache.py`
Expected: PASS (12 passed).

- [ ] **Step 6: Commit**

```bash
git add bench/task_template/ttl_cache.py bench/tests_hidden/test_ttl_cache.py bench/reference/ttl_cache.py
git commit -m "bench: TtlCache task stub + held-out grader + reference oracle"
```

---

## Task 2: Visible task surface — prompt (README) + smoke tests + pyproject

**Files:**
- Create: `bench/task_template/README.md`
- Create: `bench/task_template/tests/test_smoke.py`
- Create: `bench/task_template/pyproject.toml`

- [ ] **Step 1: Write the prompt** (`bench/task_template/README.md`) — the contract in prose, no held-out specifics leaked

````markdown
# Task: implement `TtlCache`

Implement the `TtlCache` class in `ttl_cache.py` (the file has the signatures and a
`Stats` dataclass already). It is a bounded in-memory cache combining three behaviours:

- **Capacity + LRU.** `TtlCache(capacity)` holds at most `capacity` entries. When a new
  key is inserted and the cache is full, evict the **least-recently-used** entry. Both
  `get` (on a hit) and `set` count as "using" a key. Overwriting an existing key updates
  its value and recency but must **not** evict anything.
- **Per-key TTL.** `set(key, value, ttl=...)` expires the entry `ttl` seconds from now,
  measured with the injected `clock` (default `time.monotonic`). `ttl=None` never expires.
  Expiry is lazy: an expired entry is dropped the next time it is touched (`get`, `set`,
  or `len`). A `get` on an expired key returns `None` and is a miss.
- **Stats.** The `stats` property exposes counters: `hits`, `misses`,
  `ttl_evictions` (entries dropped due to expiry), and `capacity_evictions` (live
  entries evicted to make room). `capacity=0` is legal — nothing is stored and every new
  insert is a capacity eviction.

`get` returns the value, or `None` if the key is absent or expired. `len(cache)` returns
the number of live (non-expired) entries.

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite covering all the rules above, so implement the full
contract, not just the smoke tests.
````

- [ ] **Step 2: Write the visible smoke tests** (`bench/task_template/tests/test_smoke.py`)

```python
from ttl_cache import TtlCache


def test_set_and_get():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    assert c.get("a") == 1


def test_missing_key_returns_none():
    c = TtlCache(capacity=2)
    assert c.get("nope") is None


def test_len_and_overwrite():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("a", 2)
    assert c.get("a") == 2
    assert len(c) == 1
```

- [ ] **Step 3: Write pyproject** (`bench/task_template/pyproject.toml`)

```toml
[project]
name = "ttl-cache-task"
version = "0.0.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
pythonpath = ["."]
```

- [ ] **Step 4: Smoke tests PASS against the reference, FAIL against the stub**

Run (pass): `cp bench/reference/ttl_cache.py /tmp/ref_ttl.py && cd bench/task_template && cp tests/test_smoke.py /tmp/ && (cd /tmp && cp ref_ttl.py ttl_cache.py && uv run --with pytest pytest -q test_smoke.py)`
Expected: PASS (3 passed).
Run (fail): `cd bench/task_template && uv run --with pytest pytest -q tests/test_smoke.py`
Expected: FAIL (NotImplementedError).

- [ ] **Step 5: Commit**

```bash
git add bench/task_template/README.md bench/task_template/tests/test_smoke.py bench/task_template/pyproject.toml
git commit -m "bench: visible task surface (prompt + smoke tests + pyproject)"
```

---

## Task 3: Orchestrator `bench` workspace (real-claude pipeline)

**Files:**
- Create: `bench/orchestrator_ws/.orchestrator/roles/planner.yaml`
- Create: `bench/orchestrator_ws/.orchestrator/roles/implementer.yaml`
- Create: `bench/orchestrator_ws/.orchestrator/roles/reviewer.yaml`
- Create: `bench/orchestrator_ws/.orchestrator/pipelines/bench.yaml`

- [ ] **Step 1: Roles** (three files)

`roles/planner.yaml`:
```yaml
harness: claude_code
access: read-only
```

`roles/implementer.yaml`:
```yaml
harness: claude_code
access: edit
```

`roles/reviewer.yaml`:
```yaml
harness: claude_code
access: read-only
```

- [ ] **Step 2: Pipeline** (`pipelines/bench.yaml`) — plan → implement → review⟲ → test(success_criteria)

```yaml
name: bench
steps:
  - id: plan
    type: task
    prompt: |
      Read the task in README.md (the user task is: {{task}}). Produce a short,
      concrete implementation plan for ttl_cache.py. Output only the plan.

  - id: implement
    type: agent
    role: implementer
    needs: [plan]
    prompt: |
      Implement ttl_cache.py to satisfy README.md. Plan:
      {{plan.output}}
      Run `uv run --with pytest pytest -q` until the smoke tests pass. Implement the
      FULL contract described in README.md, not only the smoke tests.
    success_criteria: "uv run --with pytest pytest -q tests/"
    max_retries: 1

  - id: review
    type: agent
    role: reviewer
    needs: [implement]
    on_reject: implement
    output_schema:
      verdict: "approve | reject"
    prompt: |
      Review ttl_cache.py against README.md for correctness and completeness of the
      full contract (LRU, TTL lazy expiry, stats counters, capacity=0). Reply with a
      JSON object {"verdict": "approve"} or {"verdict": "reject"}.
```

- [ ] **Step 3: Verify it compiles**

Run: `cd /home/user/.superset/projects/orchestrator && uv run orch compile bench --root bench/orchestrator_ws/.orchestrator`
Expected: `OK: pipeline 'bench' compiled.` with nodes plan, implement, review and a `review -?-> implement` back-edge.

- [ ] **Step 4: Commit**

```bash
git add bench/orchestrator_ws/.orchestrator
git commit -m "bench: orchestrator 'bench' pipeline (real-claude plan/implement/review loop)"
```

---

## Task 4: Runner core — repo copy + grade (zero-cost, fake contestant)

**Files:**
- Create: `bench/runner.py`
- Create: `bench/tests/test_runner.py`
- Modify: `.gitignore` (add `bench/results/`)

- [ ] **Step 1: Write the failing test** (`bench/tests/test_runner.py`)

```python
import subprocess
from pathlib import Path

from bench.runner import grade, make_repo_copy

BENCH = Path(__file__).resolve().parents[1]


def _commit_solution(repo: Path, src: Path) -> None:
    (repo / "ttl_cache.py").write_text(src.read_text())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "solve"], cwd=repo, check=True, capture_output=True)


def test_reference_solution_grades_as_pass(tmp_path):
    repo = make_repo_copy("fake-good", dest_root=tmp_path)
    _commit_solution(repo, BENCH / "reference" / "ttl_cache.py")
    result = grade(repo, hidden_dir=BENCH / "tests_hidden")
    assert result.passed is True
    assert result.failed == 0


def test_stub_grades_as_fail(tmp_path):
    repo = make_repo_copy("fake-bad", dest_root=tmp_path)  # stub left in place
    result = grade(repo, hidden_dir=BENCH / "tests_hidden")
    assert result.passed is False
    assert result.failed > 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_runner.py`
Expected: FAIL (`ModuleNotFoundError: bench.runner`).

- [ ] **Step 3: Write minimal `runner.py`** (repo copy + grade only)

```python
"""Benchmark runner: copy task → run contestant → grade against held-out tests."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BENCH = Path(__file__).resolve().parent
TASK_TEMPLATE = BENCH / "task_template"
DEFAULT_RESULTS = BENCH / "results"


def make_repo_copy(name: str, *, dest_root: Path | None = None) -> Path:
    """Copy task_template into a fresh git repo and return its path."""
    root = dest_root or DEFAULT_RESULTS
    repo = root / name / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(TASK_TEMPLATE, repo)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "bench@example.com")
    git("config", "user.name", "bench")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-qm", "task baseline")
    return repo


@dataclass
class GradeResult:
    passed: bool
    n_passed: int
    failed: int
    output: str


def grade(repo: Path, *, hidden_dir: Path) -> GradeResult:
    """Copy held-out tests into the repo, run pytest, parse, then remove them."""
    target = repo / "_hidden"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(hidden_dir, target)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "_hidden", "-p", "no:cacheprovider"],
            cwd=repo, capture_output=True, text=True,
        )
    finally:
        shutil.rmtree(target, ignore_errors=True)
    out = proc.stdout + proc.stderr
    n_passed = _count(out, "passed")
    failed = _count(out, "failed") + _count(out, "error")
    return GradeResult(passed=(proc.returncode == 0 and failed == 0),
                       n_passed=n_passed, failed=failed, output=out)


def _count(text: str, word: str) -> int:
    """Parse pytest's summary line, e.g. '12 passed' / '3 failed'."""
    import re
    m = re.search(rf"(\d+) {word}", text)
    return int(m.group(1)) if m else 0
```

Note: the grader runs with the repo's own interpreter via `python -m pytest`; the runner
invokes it inside `uv run` so pytest is available. The `_hidden/` dir is removed after
grading so it never pollutes the contestant's diff.

- [ ] **Step 4: Add `bench/results/` to .gitignore**

Append to `/home/user/.superset/projects/orchestrator/.gitignore`:
```
# Benchmark run outputs
bench/results/
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_runner.py`
Expected: PASS (2 passed). The reference solution grades pass; the stub grades fail.

- [ ] **Step 6: Commit**

```bash
git add bench/runner.py bench/tests/test_runner.py .gitignore
git commit -m "bench: runner core (repo copy + held-out grading) + fake-contestant tests"
```

---

## Task 5: Metric parsers (claude / codex / orchestrator)

**Files:**
- Create: `bench/metrics.py`
- Create: `bench/tests/test_metrics.py`

- [ ] **Step 1: Write the failing test** (`bench/tests/test_metrics.py`)

```python
from bench.metrics import Metrics, parse_claude_stream, parse_codex_jsonl


def test_parse_claude_stream_extracts_cost_and_turns():
    stream = (
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n'
        '{"type":"result","subtype":"success","total_cost_usd":0.0421,'
        '"num_turns":7,"usage":{"input_tokens":1200,"output_tokens":300},"result":"done"}\n'
    )
    m = parse_claude_stream(stream)
    assert m.cost_usd == 0.0421
    assert m.turns == 7
    assert m.tokens == 1500


def test_parse_codex_jsonl_counts_turns_and_tokens_tolerantly():
    stream = (
        '{"type":"item.completed","item":{"item_type":"assistant_message"}}\n'
        '{"type":"item.completed","item":{"item_type":"command_execution"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":2000,"output_tokens":500}}\n'
    )
    m = parse_codex_jsonl(stream)
    assert m.turns >= 1
    assert m.tokens == 2500  # summed from any usage objects seen
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_metrics.py`
Expected: FAIL (`ModuleNotFoundError: bench.metrics`).

- [ ] **Step 3: Write `metrics.py`**

```python
"""Per-contestant metric extraction. Parsers are tolerant: agent CLIs evolve."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Metrics:
    cost_usd: float | None
    tokens: int | None
    turns: int | None


def _iter_json_lines(stream: str):
    for line in stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def parse_claude_stream(stream: str) -> Metrics:
    """claude -p --output-format stream-json: cost+turns from the final `result` event."""
    cost = tokens = turns = None
    for obj in _iter_json_lines(stream):
        if obj.get("type") == "result":
            cost = float(obj.get("total_cost_usd")) if obj.get("total_cost_usd") is not None else cost
            turns = int(obj.get("num_turns")) if obj.get("num_turns") is not None else turns
            usage = obj.get("usage") or {}
            it, ot = usage.get("input_tokens"), usage.get("output_tokens")
            if it is not None or ot is not None:
                tokens = int(it or 0) + int(ot or 0)
    return Metrics(cost_usd=cost, tokens=tokens, turns=turns)


def parse_codex_jsonl(stream: str) -> Metrics:
    """codex exec --json: tolerant scan. Turns = agent/command items; tokens summed
    from any `usage` objects. Cost left None (derive externally if needed)."""
    turns = 0
    tokens = 0
    saw_tokens = False
    for obj in _iter_json_lines(stream):
        t = obj.get("type", "")
        if t.startswith("item.completed") or t.startswith("turn.completed"):
            turns += 1 if "item" in obj else 0
        usage = obj.get("usage") or (obj.get("info") or {}).get("usage")
        if isinstance(usage, dict):
            it, ot = usage.get("input_tokens"), usage.get("output_tokens")
            if it is not None or ot is not None:
                tokens += int(it or 0) + int(ot or 0)
                saw_tokens = True
    return Metrics(cost_usd=None, tokens=tokens if saw_tokens else None,
                   turns=turns if turns else None)


def orchestrator_metrics(repo_root: Path, run_id: str, span_db: Path) -> Metrics:
    """Read contestant A's cost/tokens from the orchestrator span store via `orch metrics`."""
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.cli", "metrics", run_id, "--repo", str(repo_root)],
        cwd=repo_root, capture_output=True, text=True,
        env={"ORCH_SPAN_DB": str(span_db)} | _os_environ(),
    )
    cost = _grep_float(proc.stdout, r"total: \$([0-9.]+)")
    tokens = _grep_int(proc.stdout, r"\(([0-9]+) tokens")
    return Metrics(cost_usd=cost, tokens=tokens, turns=None)  # turns filled by caller from span count


def _os_environ() -> dict:
    import os
    return dict(os.environ)


def _grep_float(text: str, pat: str) -> float | None:
    import re
    m = re.search(pat, text)
    return float(m.group(1)) if m else None


def _grep_int(text: str, pat: str) -> int | None:
    import re
    m = re.search(pat, text)
    return int(m.group(1)) if m else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_metrics.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add bench/metrics.py bench/tests/test_metrics.py
git commit -m "bench: tolerant metric parsers (claude stream-json / codex jsonl / orch metrics)"
```

---

## Task 6: Integrity scan + scorecard renderer

**Files:**
- Create: `bench/scorecard.py`
- Create: `bench/tests/test_scorecard.py`

- [ ] **Step 1: Write the failing test** (`bench/tests/test_scorecard.py`)

```python
from bench.scorecard import Row, integrity_flags, render_scorecard


def test_integrity_flags_detect_hidden_test_peeking():
    transcript = "let me look at tests_hidden/test_ttl_cache.py to see expectations"
    flags = integrity_flags(transcript, diff="def get(self,k): return 1")
    assert any("hidden" in f.lower() for f in flags)


def test_integrity_flags_clean_transcript_has_none():
    flags = integrity_flags("implementing the LRU logic now", diff="ok")
    assert flags == []


def test_render_scorecard_has_all_contestants_and_axes():
    rows = [
        Row("A orchestrator", passed=True, cost_usd=0.21, wall_s=95.0, turns=12,
            integrity=[], quality="4/5 clear naming"),
        Row("B claude code", passed=True, cost_usd=0.04, wall_s=40.0, turns=7,
            integrity=[], quality="4/5"),
        Row("C codex", passed=False, cost_usd=None, wall_s=60.0, turns=5,
            integrity=["peeked at hidden tests"], quality="2/5 incomplete"),
    ]
    md = render_scorecard(rows, task="TtlCache", verdict="A and B solved it; C did not.")
    assert "A orchestrator" in md and "C codex" in md
    assert "pass@1" in md.lower()
    assert "TtlCache" in md
    assert "peeked at hidden tests" in md
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_scorecard.py`
Expected: FAIL (`ModuleNotFoundError: bench.scorecard`).

- [ ] **Step 3: Write `scorecard.py`**

```python
"""Integrity heuristics + scorecard rendering."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Row:
    name: str
    passed: bool
    cost_usd: float | None
    wall_s: float | None
    turns: int | None
    integrity: list[str] = field(default_factory=list)
    quality: str = ""


_PEEK_MARKERS = ("tests_hidden", "_hidden/", "held-out", "hidden test")
_ESCAPE_MARKERS = ("../", "/etc/", os_sep := "")  # see below


def integrity_flags(transcript: str, *, diff: str = "") -> list[str]:
    """Heuristic integrity flags. transcript = the agent's captured stdout/session."""
    flags: list[str] = []
    low = transcript.lower()
    if any(m in low for m in _PEEK_MARKERS):
        flags.append("Referenced the hidden test path/name")
    # Hardcoded-return smell: a get() that returns a constant with no branching.
    if "return 1" in diff and "if" not in diff:
        flags.append("Possible hardcoded return (no branching logic)")
    return flags


def integrity_flags_kw(transcript, diff=""):  # back-compat alias if needed
    return integrity_flags(transcript, diff=diff)


def _cell(v) -> str:
    return "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def render_scorecard(rows: list[Row], *, task: str, verdict: str) -> str:
    lines = [
        f"# Benchmark Scorecard — `{task}`",
        "",
        "| Contestant | pass@1 | cost $ | wall s | turns | integrity | quality |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        integ = "ok" if not r.integrity else "⚠ " + "; ".join(r.integrity)
        lines.append(
            f"| {r.name} | {'✅' if r.passed else '❌'} | {_cell(r.cost_usd)} | "
            f"{_cell(r.wall_s)} | {_cell(r.turns)} | {integ} | {r.quality} |"
        )
    lines += ["", "## Verdict", "", verdict, ""]
    return "\n".join(lines)
```

Note (Step 3 cleanup): delete the stray `_ESCAPE_MARKERS` line and the `integrity_flags_kw`
alias before committing — they are not used. The committed file contains only `Row`,
`_PEEK_MARKERS`, `integrity_flags`, `_cell`, and `render_scorecard`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_scorecard.py`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add bench/scorecard.py bench/tests/test_scorecard.py
git commit -m "bench: integrity heuristics + scorecard renderer"
```

---

## Task 7: Real contestant runners + end-to-end wiring (dry-run validated)

**Files:**
- Modify: `bench/runner.py` (add `run_claude`, `run_codex`, `run_orchestrator`, `main`)
- Modify: `bench/tests/test_runner.py` (add a dry-run test using a fake-agent callable)

- [ ] **Step 1: Write the failing test** (append to `bench/tests/test_runner.py`)

```python
from bench.runner import run_contestant


def test_run_contestant_with_injected_agent_grades(tmp_path):
    # A fake "agent" that writes the reference solution; proves the run→grade
    # pipeline works end-to-end with zero model spend.
    def fake_agent(repo: Path) -> str:
        (repo / "ttl_cache.py").write_text((BENCH / "reference" / "ttl_cache.py").read_text())
        return '{"type":"result","total_cost_usd":0.01,"num_turns":3,"usage":{"input_tokens":10,"output_tokens":5}}'

    outcome = run_contestant("fake", fake_agent, dest_root=tmp_path,
                             hidden_dir=BENCH / "tests_hidden")
    assert outcome.grade.passed is True
    assert outcome.wall_s >= 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_runner.py::test_run_contestant_with_injected_agent_grades`
Expected: FAIL (`cannot import name 'run_contestant'`).

- [ ] **Step 3: Extend `runner.py`** with the contestant orchestration

```python
import os
import time
from typing import Callable

from bench.metrics import Metrics, orchestrator_metrics, parse_claude_stream, parse_codex_jsonl


@dataclass
class Outcome:
    name: str
    grade: "GradeResult"
    wall_s: float
    transcript: str
    metrics: Metrics


# An "agent" takes the repo path, mutates it in place, returns its raw transcript.
Agent = Callable[[Path], str]


def run_contestant(name: str, agent: Agent, *, dest_root: Path, hidden_dir: Path) -> Outcome:
    repo = make_repo_copy(name, dest_root=dest_root)
    start = time.monotonic()
    transcript = agent(repo)
    wall_s = time.monotonic() - start
    (repo.parent / "transcript.txt").write_text(transcript)
    g = grade(repo, hidden_dir=hidden_dir)
    return Outcome(name=name, grade=g, wall_s=wall_s, transcript=transcript, metrics=Metrics(None, None, None))


def _prompt() -> str:
    return (TASK_TEMPLATE / "README.md").read_text()


def agent_claude(repo: Path) -> str:
    proc = subprocess.run(
        ["claude", "-p", _prompt(), "--output-format", "stream-json", "--verbose",
         "--permission-mode", "acceptEdits"],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def agent_codex(repo: Path) -> str:
    proc = subprocess.run(
        ["codex", "exec", "-C", str(repo), "-s", "workspace-write", "--json", _prompt()],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def agent_orchestrator(repo: Path) -> str:
    ws = BENCH / "orchestrator_ws" / ".orchestrator"
    run_id = "bench" + str(int(time.monotonic()))
    env = dict(os.environ)
    env["ORCH_CLAUDE_BIN"] = "claude"
    env["ORCH_SPAN_DB"] = str(repo.parent / "spans.sqlite")
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.cli", "run", "bench",
         "--task", "implement TtlCache per README.md", "--root", str(ws), "--repo", str(repo)],
        cwd=repo, capture_output=True, text=True, env=env, timeout=900,
    )
    (repo.parent / "orch_run_id.txt").write_text(run_id)
    return proc.stdout + proc.stderr


def main() -> None:
    ts = time.strftime("%Y%m%d-%H%M%S")
    root = DEFAULT_RESULTS / ts
    hidden = BENCH / "tests_hidden"
    contestants = [
        ("A_orchestrator", agent_orchestrator, "orchestrator"),
        ("B_claude", agent_claude, "claude"),
        ("C_codex", agent_codex, "codex"),
    ]
    outcomes = []
    for name, agent, kind in contestants:
        print(f"=== running {name} ===")
        try:
            o = run_contestant(name, agent, dest_root=root, hidden_dir=hidden)
        except Exception as exc:  # a contestant failing is a RESULT, not a crash
            print(f"{name} FAILED: {exc}")
            o = Outcome(name, GradeResult(False, 0, 1, str(exc)), 0.0, str(exc), Metrics(None, None, None))
        if kind == "claude":
            o.metrics = parse_claude_stream(o.transcript)
        elif kind == "codex":
            o.metrics = parse_codex_jsonl(o.transcript)
        elif kind == "orchestrator":
            o.metrics = parse_claude_stream(o.transcript)  # best-effort; refine from span store
        outcomes.append((o, kind))
        print(f"{name}: pass={o.grade.passed} wall={o.wall_s:.0f}s")
    _emit_scorecard(root, outcomes)


def _emit_scorecard(root: Path, outcomes) -> None:
    from bench.scorecard import Row, integrity_flags, render_scorecard
    rows = []
    for o, _kind in outcomes:
        diff = subprocess.run(["git", "-C", str(root / o.name / "repo"), "diff", "HEAD"],
                              capture_output=True, text=True).stdout
        rows.append(Row(
            name=o.name, passed=o.grade.passed, cost_usd=o.metrics.cost_usd,
            wall_s=o.wall_s, turns=o.metrics.turns,
            integrity=integrity_flags(o.transcript, diff=diff), quality="(fill in: manual rubric)",
        ))
    verdict = "(fill in after reading diffs)"
    (root / "scorecard.md").write_text(render_scorecard(rows, task="TtlCache", verdict=verdict))
    print(f"scorecard → {root / 'scorecard.md'}")


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run the dry-run test to verify it passes**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/test_runner.py`
Expected: PASS (3 passed). The fake-agent path exercises run→grade end-to-end with no model spend.

- [ ] **Step 5: Full harness unit suite green + ruff**

Run: `cd /home/user/.superset/projects/orchestrator && uv run --with pytest pytest -q bench/tests/ && uv run ruff check bench/`
Expected: PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add bench/runner.py bench/tests/test_runner.py
git commit -m "bench: real contestant runners (claude/codex/orchestrator) + dry-run-validated main"
```

---

## Task 8: Execute the live 3-way benchmark + write findings

This task spends real money/time and is run once, manually, after Tasks 1–7 are green.

- [ ] **Step 1: Pre-flight auth check (no model spend)**

Run: `claude --version && codex --version && ls ~/.claude/.credentials.json ~/.codex/auth.json`
Expected: all present (already confirmed during brainstorming).

- [ ] **Step 2: Run the benchmark**

Run: `cd /home/user/.superset/projects/orchestrator && uv run python -m bench.runner`
Expected: three `=== running … ===` blocks, each printing `pass=… wall=…s`, then a
`scorecard → bench/results/<ts>/scorecard.md`. **If contestant A (orchestrator) errors on
its first real claude drive, capture the error — that is a headline finding (the
deferred real-vs-fake reconciliation gap), not a stop.**

- [ ] **Step 3: Source contestant A's real cost/turns from the span store**

Run: `uv run orch metrics $(cat bench/results/<ts>/A_orchestrator/orch_run_id.txt) --repo bench/results/<ts>/A_orchestrator/repo`
(If the printed CLI run-id differs, use the run-id from contestant A's stdout.) Record
cost/tokens; turns = harness-session count from `orch status`.

- [ ] **Step 4: Manual quality rubric + integrity review**

For each contestant's `repo/ttl_cache.py` diff: score readability (1–5) and
maintainability (1–5) with labeled reasons (e.g. "clear naming", "dead code", "missing
edge handling"). Confirm the heuristic integrity flags by reading the transcript.

- [ ] **Step 5: Fill in the scorecard verdict + quality cells**

Edit `bench/results/<ts>/scorecard.md`: replace the `(fill in …)` placeholders with the
rubric scores and a written verdict answering the headline question (did governance beat
the raw agents?). Note actual $ spend.

- [ ] **Step 6: Write the findings doc**

Create `docs/superpowers/notes/2026-06-08-benchmark-findings.md` summarizing: the
scorecard, the verdict, any contestant failure (esp. A's first real run) with its cause,
and follow-ups it surfaced (e.g. real-vs-fake reconciliation items now empirically
confirmed/closed).

- [ ] **Step 7: Commit the committable artifacts**

```bash
git add docs/superpowers/notes/2026-06-08-benchmark-findings.md
git commit -m "bench: live 3-way benchmark findings + verdict"
```
(`bench/results/` is gitignored; copy any keepsake scorecard into the findings doc.)

---

## Self-Review

- **Spec coverage:** contestants/invocations (Tasks 3,7) · TtlCache task + visible/hidden split (Tasks 1,2) · harness components repo-copy/run/metrics/grade/integrity/scorecard (Tasks 4–7) · four scorecard axes (Tasks 5,6,8) · fairness rules (identical template+prompt in Tasks 4,7; visible-only success_criteria in Task 3) · risks incl. A's real-run-as-finding (Task 8 Step 2) · cost reporting (Task 8 Step 5). All covered.
- **Placeholder scan:** the only intentional "(fill in …)" strings live in the *generated* scorecard and are explicitly completed by hand in Task 8 Steps 4–5 (the experiment's payload, not plan gaps). Task 6 Step 3 flags two stray lines to delete before commit.
- **Type consistency:** `Metrics(cost_usd, tokens, turns)`, `GradeResult(passed, n_passed, failed, output)`, `Outcome(name, grade, wall_s, transcript, metrics)`, `Row(name, passed, cost_usd, wall_s, turns, integrity, quality)`, `run_contestant`, `make_repo_copy`, `grade`, `integrity_flags`, `render_scorecard` are used consistently across Tasks 4–8.
