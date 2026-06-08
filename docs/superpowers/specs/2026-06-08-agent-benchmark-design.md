# Spec: Governed-vs-Raw Coding-Agent Benchmark (2026-06-08)

## 1. Goal & question

Run **one identical, objectively-graded coding task** through three contestants and
compare them on a four-axis scorecard. The headline question:

> Does the orchestrator's **governed pipeline** (worktree isolation → plan →
> implement → review⟲ → test gate, driving the *real* `claude` binary) produce a
> better outcome than the **raw single-shot agents** `claude code` and `codex` on
> the same task?

This is the small-scale, industry-sanctioned form of agent evaluation ("run one
end-to-end work item through your normal process and compare"), graded objectively
against a **held-out test suite** the agents never see (SWE-bench's Fail-to-Pass /
Pass-to-Pass pattern, reported as **pass@1**).

## 2. Contestants

All three get the **identical starting repo** (a fresh copy per contestant) and the
**identical prompt** (the task `README`), run **non-interactively** with a wall-clock
timer, with edit-autonomy parity (auto-accept edits / workspace-write sandbox).

| # | Contestant | Invocation (cwd = the contestant's repo copy) |
|---|------------|-----------------------------------------------|
| **A** | **orchestrator** | `ORCH_CLAUDE_BIN=claude orch run bench --task "<prompt>" --repo <repo>` — a real `plan → implement → review⟲ → test` pipeline driving the real `claude` binary. |
| **B** | **claude code** (raw) | `claude -p "<prompt>" --output-format stream-json --verbose --permission-mode acceptEdits` |
| **C** | **codex** (raw) | `codex exec -C <repo> -s workspace-write --json "<prompt>"` |

Contestant A is the project's value proposition under test. **It has never made a
real harness run** (all milestones used zero-cost fakes; M6a/M6b flag real-vs-fake
stream-json/flag reconciliation as *unverified*). Per the approved decision, we run
all three directly; **if A fails on its first real drive, that failure and its cause
are a headline result**, not something we pre-fix.

## 3. The task — `TtlCache`

A bespoke task (resists training-set contamination) with rich edge cases (a good
discriminator) and an injected clock (deterministic, gradeable).

**Visible contract** (`ttl_cache.py` stub + `README`, both in the repo):

```python
class TtlCache:
    """Bounded in-memory cache: per-key TTL + LRU eviction + stats."""
    def __init__(self, capacity: int, *, clock: Callable[[], float] = time.monotonic) -> None: ...
    def set(self, key: Hashable, value: Any, *, ttl: float | None = None) -> None: ...
    def get(self, key: Hashable) -> Any | None: ...
    def __len__(self) -> int: ...
    @property
    def stats(self) -> Stats: ...   # dataclass: hits, misses, ttl_evictions, capacity_evictions
```

**Semantics (the held-out tests pin these exactly):**
- **LRU recency:** both `get` (on a live hit) and `set` (new or overwrite) mark the key
  most-recently-used.
- **Capacity:** inserting a *new* key when `len == capacity` evicts the LRU **live**
  entry and increments `capacity_evictions`. Overwriting an existing key never evicts.
- **TTL:** `ttl=None` (default) = never expires; a per-`set` `ttl` is seconds against
  `clock()`. Expiry is **lazy**: an expired entry is removed on the next `get`/`set`/`len`
  touch. A `get` on an expired key is a **miss** and increments `ttl_evictions`.
- **`len`:** counts only **live** (non-expired) entries (lazily purges as it counts).
- **`stats`:** `hits` (live `get` hit), `misses` (absent or expired `get`),
  `ttl_evictions`, `capacity_evictions`. `capacity=0` is legal (nothing is ever stored;
  every `set` of a new key is an immediate capacity eviction).

**Visible smoke tests** (`tests/test_smoke.py`, in the repo, ~3 tests): basic
`set`/`get`/`len`/overwrite — enough for an agent to self-verify partially, not enough
to reverse-engineer the full spec.

**Held-out grader** (`bench/tests_hidden/test_ttl_cache.py`, ~15 tests, NEVER in any
repo): LRU order under interleaved get/set, capacity eviction + overwrite-no-evict,
TTL lazy expiry across get/len, the four stats counters, `capacity=0`, and clock
determinism. **pass@1 = this suite goes green on the agent's first submission.**

## 4. Repo layout

```
bench/
  task_template/            # copied fresh into each contestant's repo
    ttl_cache.py            #   stub w/ signatures + docstring contract
    README.md               #   the task description = the prompt
    tests/test_smoke.py     #   visible smoke tests
    pyproject.toml          #   pytest runnable
  tests_hidden/
    test_ttl_cache.py       # the held-out grader (applied equally, post-run)
  orchestrator_ws/.orchestrator/   # the `bench` pipeline + real-claude roles for contestant A
  runner.py                 # orchestrates the whole experiment (see §5)
  results/<timestamp>/
    A_orchestrator/ B_claude/ C_codex/   # per-contestant repo + captured stdout/metrics
    scorecard.md
```

`bench/` lives in the orchestrator repo (version-controlled, reproducible). Results
under `bench/results/` are gitignored.

## 5. Harness architecture

`runner.py` — small, single-purpose components:

1. **`make_repo_copy(contestant) -> Path`** — copy `task_template/` into
   `results/<ts>/<contestant>/repo`, `git init` + initial commit (clean baseline diff).
2. **`run_A_orchestrator(repo)` / `run_B_claude(repo)` / `run_C_codex(repo)`** — each
   spawns its CLI (§2) with a monotonic timer, capturing stdout/stderr to files and
   returning a `RunResult(wall_s, raw_metrics)`. The orchestrator's `test` gate runs
   the **visible** smoke tests only (never the held-out grader).
3. **`collect_metrics(contestant, run)` -> `Metrics`** — per-contestant sourcing (§6).
4. **`grade(repo) -> GradeResult`** — copy `tests_hidden/` into the repo, run
   `pytest -q tests_hidden/`, parse pass/fail counts; remove hidden tests after. pass@1
   = all held-out tests pass.
5. **`integrity_scan(contestant, repo, transcript) -> list[Flag]`** — heuristics (§6).
6. **`write_scorecard(rows)`** — render `scorecard.md`.

Each contestant runs in a **fresh git repo** off the same template → strong isolation,
no cross-contamination, clean per-contestant diff for the quality rubric.

## 6. Metrics & grading (the four axes)

- **① pass@1 (objective)** — held-out pytest suite green on first submission. Primary.
- **② efficiency** — wall-clock (runner timer, all three); cost $ and turns:
  - A: `orch metrics <run_id>` + `orch status` (cost/tokens/per-step duration from the
    span store; turns = harness-session count).
  - B: parse `stream-json` — `total_cost_usd` from the `result` event; turns = assistant
    message count.
  - C: parse `--json` JSONL — token usage events → cost via OpenAI pricing; turns =
    agent-turn count. (If codex doesn't emit usable usage, report turns + wall-clock and
    mark cost "n/a".)
- **③ integrity** — held-out tests live OUTSIDE every repo, so peeking is structurally
  hard. Flags: agent searched for / referenced hidden-test paths; hardcoded magic return
  values instead of real logic; wrote/read outside its repo dir. Heuristic scan of the
  transcript + diff, plus a manual LLM-judge read.
- **④ quality rubric** — I read each final diff and score **readability** and
  **maintainability** (1–5) with **labeled reasons** (e.g. "clear naming", "dead code",
  "missing edge handling"), per the 2025 enterprise-eval guidance (label the *why*).

## 7. Fairness rules

- Identical starting repo + identical prompt for all three.
- Edit-autonomy parity: B `--permission-mode acceptEdits`, C `-s workspace-write`, A's
  edit role resolves to accept-edits. None get network beyond their model API.
- No contestant ever sees the held-out grader; A's internal `test` gate uses visible
  smoke tests only.
- Same single attempt = pass@1 for all (A's *internal* review⟲ retries are part of "the
  orchestrator system under test" — that governance IS contestant A; its one final
  submission is still graded once. This is the governed-vs-raw comparison, stated openly.)
- Same wall-clock cap (e.g. 10 min/contestant); a timeout is a non-pass with the reason
  recorded.

## 8. Risks & cost

- 💸 **Real spend** — three real agents (A on Opus with a review loop) on one task ≈ a
  few dollars + a few minutes each. One task bounds it; actual spend is reported.
- ⚠️ **A's first real run** may hit unverified real-`claude` stream-json/flag/MCP gaps →
  treated as a finding (see §2).
- **codex usage/cost parsing** may be incomplete → degrade gracefully to turns +
  wall-clock (§6).
- **Auth**: claude (OAuth creds), codex (`auth.json` + `OPENAI_API_KEY`), opencode
  (`auth.json`) all confirmed present; not re-verified until run time.

## 9. Out of scope

Multi-task suites, SWE-bench dataset/Docker, pass@k retry budgets, the OpenCode
contestant (A already exercises a harness; adding a 4th is noise), statistical
significance across many tasks. One task = a directional result, not a leaderboard.

## 10. Success criteria for the experiment

A committed `scorecard.md` that, for all three contestants, reports pass@1 (held-out
tests), cost/wall-clock/turns, integrity flags, and a quality-rubric score with labeled
reasons — plus a written verdict on the headline question and an honest record of any
contestant (esp. A) that failed and why.
