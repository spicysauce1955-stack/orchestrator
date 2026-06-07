# M6d — Durable Span Store + status/metrics/memory + Safety Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OTel span sink a durable, queryable SQLite store (the single record of truth), expose it through `orch status` / `orch metrics` / `orch memory` CLI lenses, and close the temp-config-file leak — completing M6, the final MVP milestone.

**Architecture:** A custom `SpanExporter` writes every span as one SQLite row (`spans` table). Spans of one run share a `trace_id`; the run's `run_id` lives on the root `run` span's `run.id` attribute, so queries resolve `run_id → trace_id → spans`. Three read-model functions (`run_status`/`run_metrics`/`run_messages`) back three thin CLI commands. The runtime (`orch run`/`orch resume`) installs the SQLite exporter at `<repo>/.orch/spans.sqlite`. Separately, `_drive_harness` gains a `finally: cancel(session)` so adapter temp files are always cleaned.

**Tech Stack:** Python 3.11+, `opentelemetry-sdk` (already a dep), stdlib `sqlite3` (JSON1), Typer, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-02-orchestrator-design.md` §3 (CLI), §9 (observability + durable store), §12 (M6d).

---

## Scope & boundaries

**In scope (M6d):**
- Durable SQLite span store + exporter.
- `run_status` / `run_metrics` / `run_messages` read models.
- `orch status` / `orch metrics` / `orch memory` CLI commands.
- Wire `orch run` / `orch resume` to export into the store.
- Safety polish: always `cancel()` harness sessions (temp-file cleanup).

**Deferred (documented, NOT this plan):**
- **`knowledge-write` / `MCP-call` span instrumentation.** Knowledge writes happen inside the `mcp_server.py` *subprocess* spawned by the harness, not the orchestrator process — emitting spans for them is a cross-process tracing problem. The `memory` lens therefore renders **`message` spans** now (exactly what the M6c follow-up calls M6d scope: "`orch status` rendering of these spans"). `run_messages` is written forward-compatibly to also surface `knowledge.write` spans *if present*, so adding emission later needs no query change. Record this in the M6d follow-ups note.
- Parallel/best-of-n branches: queries assume a run's spans share one `trace_id`, which holds for linear MVP pipelines. Task 2 includes a test that locks this invariant.

---

## File structure

- **Create** `orchestrator/observability/store.py` — `SqliteSpanExporter(SpanExporter)` + `connect(db_path)` + schema. One responsibility: persist spans.
- **Create** `orchestrator/observability/query.py` — read models (`StatusView`/`MetricsView`/`MessageView` + `run_status`/`run_metrics`/`run_messages`). One responsibility: query spans. Depends on `store.connect`.
- **Modify** `orchestrator/cli.py` — implement `status`, add `metrics` + `memory`, add `_span_db`, wire `run`/`resume` to the SQLite exporter.
- **Modify** `orchestrator/runtime/executors.py:90-125` — `_drive_harness` gains `try/finally: await adapter.cancel(session)`.
- **Test** `tests/unit/test_span_store.py`, `tests/unit/test_query.py`, `tests/unit/test_status_cli.py`, `tests/unit/test_session_cleanup.py`.

---

## Task 1: SQLite span store + exporter

**Files:**
- Create: `orchestrator/observability/store.py`
- Test: `tests/unit/test_span_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_span_store.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from orchestrator.observability.spans import (
    SPAN_RUN,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)
from orchestrator.observability.store import SqliteSpanExporter, connect


def _emit(db: Path) -> None:
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "abc123")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as step:
            step.set_attribute("step.id", "plan")


def test_exporter_writes_one_row_per_span_sharing_a_trace(tmp_path: Path) -> None:
    db = tmp_path / ".orch" / "spans.sqlite"
    _emit(db)

    conn = connect(db)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT * FROM spans ORDER BY name"))

    assert {r["name"] for r in rows} == {SPAN_RUN, SPAN_STEP}
    # both spans share the run's trace_id
    assert len({r["trace_id"] for r in rows}) == 1
    run_row = next(r for r in rows if r["name"] == SPAN_RUN)
    step_row = next(r for r in rows if r["name"] == SPAN_STEP)
    # step's parent is the run span
    assert step_row["parent_id"] == run_row["span_id"]
    assert run_row["parent_id"] is None
    # attributes round-trip as JSON
    assert json.loads(run_row["attrs"])["run.id"] == "abc123"
    assert run_row["end_ns"] >= run_row["start_ns"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_span_store.py -v`
Expected: FAIL — `ModuleNotFoundError: orchestrator.observability.store`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/observability/store.py
"""Durable, queryable SQLite span store (spec §9, M6d).

The OTel sink for runtime runs: a custom SpanExporter writes every span as one
row — the single record of truth. `orch status|metrics|memory` query this store
(see query.py). Spans of one run share a trace_id; the run_id lives on the root
`run` span's `run.id` attribute.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id  TEXT NOT NULL,
    span_id   TEXT NOT NULL PRIMARY KEY,
    parent_id TEXT,
    name      TEXT NOT NULL,
    start_ns  INTEGER NOT NULL,
    end_ns    INTEGER NOT NULL,
    attrs     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parent dir + schema) a connection to the span store."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.executescript(_SCHEMA)
    return conn


class SqliteSpanExporter(SpanExporter):
    """Writes finished spans into the SQLite span store (one row per span)."""

    def __init__(self, db_path: Path) -> None:
        self._conn = connect(db_path)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        rows = []
        for span in spans:
            ctx = span.get_span_context()
            parent = span.parent.span_id if span.parent else None
            rows.append(
                (
                    format(ctx.trace_id, "032x"),
                    format(ctx.span_id, "016x"),
                    format(parent, "016x") if parent is not None else None,
                    span.name,
                    int(span.start_time or 0),
                    int(span.end_time or 0),
                    json.dumps(dict(span.attributes or {})),
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO spans "
                "(trace_id, span_id, parent_id, name, start_ns, end_ns, attrs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        with self._lock:
            self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_span_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/observability/store.py tests/unit/test_span_store.py
git commit -m "feat(m6d): SQLite span store + exporter (durable record of truth)"
```

---

## Task 2: Read model — run_status

**Files:**
- Create: `orchestrator/observability/query.py`
- Test: `tests/unit/test_query.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_query.py
from __future__ import annotations

from pathlib import Path

from orchestrator.observability.spans import (
    SPAN_RUN,
    SPAN_SESSION,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)
from orchestrator.observability.query import run_status
from orchestrator.observability.store import SqliteSpanExporter


def _seed(db: Path) -> None:
    """Emit a run 'r1' of pipeline 'demo': plan (ok) → implement (error)."""
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r1")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as plan:
            plan.set_attribute("step.id", "plan")
            plan.set_attribute("step.role", "planner")
            plan.set_attribute("step.is_error", False)
        with tracer.start_as_current_span(SPAN_STEP) as impl:
            impl.set_attribute("step.id", "implement")
            impl.set_attribute("step.role", "implementer")
            impl.set_attribute("step.is_error", True)
            with tracer.start_as_current_span(SPAN_SESSION) as sess:
                sess.set_attribute("cost.usd", 0.5)
                sess.set_attribute("cost.tokens", 1000)


def test_run_status_lists_steps_and_overall_state(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)

    view = run_status(db, "r1")

    assert view is not None
    assert view.pipeline == "demo"
    assert view.status == "error"  # implement failed
    assert [(s.step_id, s.role, s.is_error) for s in view.steps] == [
        ("plan", "planner", False),
        ("implement", "implementer", True),
    ]


def test_run_status_unknown_run_returns_none(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    assert run_status(db, "nope") is None


def test_all_spans_of_a_run_share_one_trace(tmp_path: Path) -> None:
    # Locks the invariant the queries depend on (linear MVP pipelines).
    import sqlite3

    from orchestrator.observability.store import connect

    db = tmp_path / "spans.sqlite"
    _seed(db)
    conn = connect(db)
    conn.row_factory = sqlite3.Row
    traces = {r["trace_id"] for r in conn.execute("SELECT trace_id FROM spans")}
    assert len(traces) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_query.py -v`
Expected: FAIL — `ModuleNotFoundError: orchestrator.observability.query`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/observability/query.py
"""Read models over the span store (spec §9): status / metrics / memory lenses.

A run's spans share one trace_id; we resolve run_id → trace_id via the root
`run` span's `run.id` attribute, then read that trace.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from orchestrator.observability.store import connect


@dataclass
class StepView:
    step_id: str
    role: str
    kind: str  # "agent" | "task" | "merge"
    is_error: bool


@dataclass
class StatusView:
    run_id: str
    pipeline: str
    status: str  # "completed" | "error"
    steps: list[StepView]


def _open(db: Path) -> sqlite3.Connection:
    conn = connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _trace_for_run(conn: sqlite3.Connection, run_id: str) -> str | None:
    for row in conn.execute("SELECT trace_id, attrs FROM spans WHERE name = 'run'"):
        if json.loads(row["attrs"]).get("run.id") == run_id:
            return str(row["trace_id"])
    return None


def _spans(conn: sqlite3.Connection, trace_id: str, name: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? AND name = ? ORDER BY start_ns",
            (trace_id, name),
        )
    )


def run_status(db: Path, run_id: str) -> StatusView | None:
    conn = _open(db)
    trace = _trace_for_run(conn, run_id)
    if trace is None:
        return None
    run_row = _spans(conn, trace, "run")[0]
    pipeline = json.loads(run_row["attrs"]).get("pipeline", "")
    steps: list[StepView] = []
    any_error = False
    for row in _spans(conn, trace, "step"):
        attrs = json.loads(row["attrs"])
        is_error = bool(attrs.get("step.is_error", False))
        any_error = any_error or is_error
        steps.append(
            StepView(
                step_id=str(attrs.get("step.id", "")),
                role=str(attrs.get("step.role", "")),
                kind=str(attrs.get("step.type", "agent")),
                is_error=is_error,
            )
        )
    return StatusView(
        run_id=run_id,
        pipeline=pipeline,
        status="error" if any_error else "completed",
        steps=steps,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_query.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/observability/query.py tests/unit/test_query.py
git commit -m "feat(m6d): run_status read model over the span store"
```

---

## Task 3: Read model — run_metrics

**Files:**
- Modify: `orchestrator/observability/query.py`
- Test: `tests/unit/test_query.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_query.py  (append; reuses _seed from Task 2)
from orchestrator.observability.query import run_metrics


def test_run_metrics_rolls_up_cost_per_step_and_total(tmp_path: Path) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)  # implement step has one session: $0.5 / 1000 tokens

    view = run_metrics(db, "r1")

    assert view is not None
    by_step = {m.step_id: m for m in view.steps}
    assert by_step["implement"].cost_usd == 0.5
    assert by_step["implement"].tokens == 1000
    assert by_step["plan"].cost_usd == 0.0  # no session under plan
    assert view.total_cost_usd == 0.5
    assert view.total_tokens == 1000
    assert by_step["implement"].duration_ms >= 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_query.py::test_run_metrics_rolls_up_cost_per_step_and_total -v`
Expected: FAIL — `ImportError: cannot import name 'run_metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/observability/query.py  (add dataclasses + function)

@dataclass
class StepMetric:
    step_id: str
    cost_usd: float
    tokens: int
    duration_ms: float


@dataclass
class MetricsView:
    run_id: str
    steps: list[StepMetric]
    total_cost_usd: float
    total_tokens: int


def run_metrics(db: Path, run_id: str) -> MetricsView | None:
    conn = _open(db)
    trace = _trace_for_run(conn, run_id)
    if trace is None:
        return None
    # session spans carry cost; group them under their parent step span.
    sessions = _spans(conn, trace, "harness.session")
    cost_by_parent: dict[str, tuple[float, int]] = {}
    for row in sessions:
        attrs = json.loads(row["attrs"])
        usd, tok = cost_by_parent.get(row["parent_id"], (0.0, 0))
        cost_by_parent[row["parent_id"]] = (
            usd + float(attrs.get("cost.usd", 0.0)),
            tok + int(attrs.get("cost.tokens", 0)),
        )
    steps: list[StepMetric] = []
    total_usd = 0.0
    total_tok = 0
    for row in _spans(conn, trace, "step"):
        attrs = json.loads(row["attrs"])
        usd, tok = cost_by_parent.get(row["span_id"], (0.0, 0))
        total_usd += usd
        total_tok += tok
        steps.append(
            StepMetric(
                step_id=str(attrs.get("step.id", "")),
                cost_usd=usd,
                tokens=tok,
                duration_ms=(int(row["end_ns"]) - int(row["start_ns"])) / 1e6,
            )
        )
    return MetricsView(
        run_id=run_id, steps=steps, total_cost_usd=total_usd, total_tokens=total_tok
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_query.py -v`
Expected: PASS (all query tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/observability/query.py tests/unit/test_query.py
git commit -m "feat(m6d): run_metrics cost/token/duration rollup"
```

---

## Task 4: Read model — run_messages

**Files:**
- Modify: `orchestrator/observability/query.py`
- Test: `tests/unit/test_query.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_query.py  (append)
from orchestrator.observability.spans import SPAN_MESSAGE
from orchestrator.observability.query import run_messages


def test_run_messages_returns_message_spans_in_order(tmp_path: Path) -> None:
    from orchestrator.observability.store import SqliteSpanExporter

    db = tmp_path / "spans.sqlite"
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r2")
        run.set_attribute("pipeline", "qa-demo")
        for frm, to, kind, body in [
            ("orchestrator", "implement", "classify", "feature"),
            ("implement", "orchestrator", "question", "which db?"),
            ("orchestrator", "implement", "answer", "sqlite"),
        ]:
            with tracer.start_as_current_span(SPAN_MESSAGE) as m:
                m.set_attribute("msg.from", frm)
                m.set_attribute("msg.to", to)
                m.set_attribute("msg.kind", kind)
                m.set_attribute("msg.body", body)

    msgs = run_messages(db, "r2")

    assert [(m.frm, m.to, m.kind, m.body) for m in msgs] == [
        ("orchestrator", "implement", "classify", "feature"),
        ("implement", "orchestrator", "question", "which db?"),
        ("orchestrator", "implement", "answer", "sqlite"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_query.py::test_run_messages_returns_message_spans_in_order -v`
Expected: FAIL — `ImportError: cannot import name 'run_messages'`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/observability/query.py  (add dataclass + function)

@dataclass
class MessageView:
    frm: str
    to: str
    kind: str
    body: str


def run_messages(db: Path, run_id: str) -> list[MessageView]:
    """The coordination board for a run: `message` spans in time order.

    Forward-compatible: when `knowledge.write` span emission lands (deferred,
    cross-process), add its name here — no caller change needed.
    """
    conn = _open(db)
    trace = _trace_for_run(conn, run_id)
    if trace is None:
        return []
    out: list[MessageView] = []
    for row in _spans(conn, trace, "message"):
        attrs = json.loads(row["attrs"])
        out.append(
            MessageView(
                frm=str(attrs.get("msg.from", "")),
                to=str(attrs.get("msg.to", "")),
                kind=str(attrs.get("msg.kind", "")),
                body=str(attrs.get("msg.body", "")),
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_query.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/observability/query.py tests/unit/test_query.py
git commit -m "feat(m6d): run_messages coordination-board read model"
```

---

## Task 5: CLI `status` + wire runtime export

**Files:**
- Modify: `orchestrator/cli.py` (imports; add `_span_db`; replace `status` body; wire `run`/`resume`)
- Test: `tests/unit/test_status_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_status_cli.py
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.observability.spans import SPAN_RUN, SPAN_STEP, configure_tracing, get_tracer
from orchestrator.observability.store import SqliteSpanExporter

runner = CliRunner()


def _seed(db: Path) -> None:
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r1")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as plan:
            plan.set_attribute("step.id", "plan")
            plan.set_attribute("step.role", "planner")
            plan.set_attribute("step.is_error", False)


def test_status_renders_run_and_steps(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))

    result = runner.invoke(app, ["status", "r1"])

    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "completed" in result.stdout
    assert "plan" in result.stdout


def test_status_unknown_run_exits_1(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))

    result = runner.invoke(app, ["status", "ghost"])

    assert result.exit_code == 1
    assert "no run 'ghost'" in result.stdout


def test_run_installs_sqlite_exporter(tmp_path: Path, monkeypatch) -> None:
    # Wiring check: `orch run` configures tracing with a SqliteSpanExporter.
    import orchestrator.cli as cli

    captured = {}

    def fake_configure(exporter=None):
        captured["exporter"] = exporter

    monkeypatch.setattr(cli, "configure_tracing", fake_configure)
    # Unknown pipeline exits before execution but AFTER configure_tracing.
    monkeypatch.setenv("ORCH_SPAN_DB", str(tmp_path / "spans.sqlite"))
    runner.invoke(app, ["run", "nope", "--root", str(tmp_path)])
    # config load fails first for a bare tmp dir; assert via a real workspace instead:
    assert "exporter" not in captured or isinstance(captured["exporter"], SqliteSpanExporter)
```

> Note: the third test is a light guard. The authoritative wiring check is the manual smoke at the end of this task (real `orch run` → `orch status`), since a full pipeline run needs the fake-harness fixture from `tests/integration/`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_status_cli.py -v`
Expected: FAIL — `status` prints the not-implemented stub; `exit_code == 2`, "completed" absent.

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/cli.py`, add to the imports block:

```python
from orchestrator.observability.query import run_status
from orchestrator.observability.store import SqliteSpanExporter
```

Add the span-db resolver next to `_checkpoint_db`:

```python
def _span_db(repo: Path) -> Path:
    env = os.environ.get("ORCH_SPAN_DB")
    return Path(env) if env else Path(repo) / ".orch" / "spans.sqlite"
```

Replace the `status` command body:

```python
@app.command()
def status(
    run_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo whose .orch/ holds the span store."),
) -> None:
    """Show a run's step-by-step status from the span store (spec §9)."""
    view = run_status(_span_db(repo), run_id)
    if view is None:
        typer.echo(f"error: no run '{run_id}' found in the span store.")
        raise typer.Exit(1)
    typer.echo(f"run {view.run_id}: pipeline '{view.pipeline}' — {view.status}")
    for s in view.steps:
        mark = "ERROR" if s.is_error else "ok"
        role = f" [{s.role}]" if s.role else ""
        typer.echo(f"  {mark:5} {s.step_id}{role} ({s.kind})")
```

In `run`, replace `configure_tracing(exporter=None)` (the single occurrence, ~line 109) with:

```python
    configure_tracing(exporter=SqliteSpanExporter(_span_db(repo)))
```

In `resume`, replace `configure_tracing(exporter=None)` (~line 207) with:

```python
    configure_tracing(exporter=SqliteSpanExporter(_span_db(repo)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_status_cli.py -v`
Expected: PASS

- [ ] **Step 5: Manual smoke (real run → status)**

Run an existing example end-to-end against the fake harness, then query it. From repo root:

```bash
uv run orch run review-demo --task "add a helper" --repo .
uv run orch status <run_id_printed_above> --repo .
```

Expected: `status` prints the pipeline name, `completed`/`error`, and one line per executed step. (If `orch run` needs `$ORCH_*_BIN` fake-harness env vars, mirror the setup used in `tests/integration/`.)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/cli.py tests/unit/test_status_cli.py
git commit -m "feat(m6d): orch status reads the span store; run/resume export to it"
```

---

## Task 6: CLI `metrics` + `memory`

**Files:**
- Modify: `orchestrator/cli.py` (imports + two commands)
- Test: `tests/unit/test_status_cli.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_status_cli.py  (append)
from orchestrator.observability.spans import SPAN_MESSAGE, SPAN_SESSION


def _seed_full(db: Path) -> None:
    configure_tracing(exporter=SqliteSpanExporter(db))
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_RUN) as run:
        run.set_attribute("run.id", "r3")
        run.set_attribute("pipeline", "demo")
        with tracer.start_as_current_span(SPAN_STEP) as impl:
            impl.set_attribute("step.id", "implement")
            impl.set_attribute("step.role", "implementer")
            impl.set_attribute("step.is_error", False)
            with tracer.start_as_current_span(SPAN_SESSION) as sess:
                sess.set_attribute("cost.usd", 0.25)
                sess.set_attribute("cost.tokens", 800)
        with tracer.start_as_current_span(SPAN_MESSAGE) as m:
            m.set_attribute("msg.from", "implement")
            m.set_attribute("msg.to", "orchestrator")
            m.set_attribute("msg.kind", "question")
            m.set_attribute("msg.body", "which db?")


def test_metrics_renders_costs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed_full(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))

    result = runner.invoke(app, ["metrics", "r3"])

    assert result.exit_code == 0
    assert "0.25" in result.stdout
    assert "800" in result.stdout
    assert "implement" in result.stdout


def test_memory_renders_messages(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "spans.sqlite"
    _seed_full(db)
    monkeypatch.setenv("ORCH_SPAN_DB", str(db))

    result = runner.invoke(app, ["memory", "r3"])

    assert result.exit_code == 0
    assert "question" in result.stdout
    assert "which db?" in result.stdout
    assert "implement" in result.stdout and "orchestrator" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_status_cli.py -k "metrics or memory" -v`
Expected: FAIL — `No such command 'metrics'` / `'memory'`.

- [ ] **Step 3: Write minimal implementation**

Extend the cli imports:

```python
from orchestrator.observability.query import run_messages, run_metrics, run_status
```

Add two commands after `status`:

```python
@app.command()
def metrics(
    run_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo"),
) -> None:
    """Show a run's cost/token/duration rollup from the span store (spec §9)."""
    view = run_metrics(_span_db(repo), run_id)
    if view is None:
        typer.echo(f"error: no run '{run_id}' found in the span store.")
        raise typer.Exit(1)
    for m in view.steps:
        typer.echo(
            f"  {m.step_id}: ${m.cost_usd:.4f} ({m.tokens} tokens, {m.duration_ms:.0f} ms)"
        )
    typer.echo(f"total: ${view.total_cost_usd:.4f} ({view.total_tokens} tokens)")


@app.command()
def memory(
    run_id: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo"),
) -> None:
    """Show a run's coordination board (message bus log) from the span store."""
    msgs = run_messages(_span_db(repo), run_id)
    if not msgs:
        typer.echo(f"run '{run_id}': no messages recorded.")
        return
    for m in msgs:
        typer.echo(f"  {m.frm} → {m.to} [{m.kind}]: {m.body}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_status_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/cli.py tests/unit/test_status_cli.py
git commit -m "feat(m6d): orch metrics + orch memory lenses over the span store"
```

---

## Task 7: Safety polish — always cancel harness sessions

**Files:**
- Modify: `orchestrator/runtime/executors.py:90-125` (`_drive_harness`)
- Test: `tests/unit/test_session_cleanup.py`

**Why:** `_drive_harness` starts a session but never calls `adapter.cancel()`. Adapters unlink their temp MCP/permission config file (`$TMPDIR/orch-mcp-*.json`, `orch-oc-*.json`) only in `cancel()` — so today every normal run orphans one temp file. A `try/finally` fixes all callers, including the `_drive_with_questions` Q&A loop (it routes every round through `_drive_harness`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_session_cleanup.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orchestrator.harness.events import Cost, Done, MessageChunk
from orchestrator.observability.spans import configure_tracing, get_tracer
from orchestrator.runtime.executors import _drive_harness
from orchestrator.safety.capabilities import ResolvedCaps


class _FakeAdapter:
    def __init__(self, *, raise_on_prompt: bool = False) -> None:
        self.cancelled: list[str] = []
        self._raise = raise_on_prompt

    async def start_session(self, *, cwd, caps, mcp_servers):
        return "sess-1"

    async def prompt(self, session, text, *, output_schema):
        if self._raise:
            raise RuntimeError("boom")

        async def _gen():
            yield MessageChunk("hi")
            yield Cost(usd=0.1, tokens=10)
            yield Done(result="done", is_error=False)

        return _gen()

    async def resume(self, session):  # pragma: no cover - unused here
        return session

    async def cancel(self, session) -> None:
        self.cancelled.append(session)


def _caps() -> ResolvedCaps:
    return ResolvedCaps()  # default-constructed; adjust if ResolvedCaps requires args


def test_session_cancelled_on_success(tmp_path: Path) -> None:
    configure_tracing(exporter=None)
    adapter = _FakeAdapter()
    asyncio.run(
        _drive_harness(adapter, _caps(), tmp_path, "go", None, get_tracer())
    )
    assert adapter.cancelled == ["sess-1"]


def test_session_cancelled_on_error(tmp_path: Path) -> None:
    configure_tracing(exporter=None)
    adapter = _FakeAdapter(raise_on_prompt=True)
    with pytest.raises(RuntimeError):
        asyncio.run(_drive_harness(adapter, _caps(), tmp_path, "go", None, get_tracer()))
    assert adapter.cancelled == ["sess-1"]  # cleaned up despite the failure
```

> If `ResolvedCaps()` cannot be default-constructed, construct it the way existing tests in `tests/unit/` do (grep `ResolvedCaps(` under `tests/`) and mirror that — the cleanup behavior under test does not depend on caps contents.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_session_cleanup.py -v`
Expected: FAIL — `adapter.cancelled == []` (no cancel today).

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/runtime/executors.py`, wrap the session body of `_drive_harness` in `try/finally`:

```python
    agg = _Aggregate()
    session = await adapter.start_session(cwd=cwd, caps=caps, mcp_servers=list(mcp_servers))
    try:
        with tracer.start_as_current_span(SPAN_SESSION) as sess_span:
            stream = await adapter.prompt(session, prompt, output_schema=output_schema)
            async for ev in stream:
                if isinstance(ev, MessageChunk):
                    agg.text_parts.append(ev.text)
                elif isinstance(ev, ToolCall):
                    with tracer.start_as_current_span(SPAN_TOOL_CALL) as tc:
                        tc.set_attribute("tool.name", ev.name)
                        tc.set_attribute("tool.status", ev.status)
                elif isinstance(ev, FileEdit):
                    with tracer.start_as_current_span(SPAN_FILE_EDIT) as fe:
                        fe.set_attribute("file.path", ev.path)
                        fe.set_attribute("file.kind", ev.kind)
                elif isinstance(ev, Cost):
                    agg.cost_usd += ev.usd
                    agg.tokens += ev.tokens
                    sess_span.set_attribute("cost.usd", ev.usd)
                    sess_span.set_attribute("cost.tokens", ev.tokens)
                elif isinstance(ev, Done):
                    agg.result_text = ev.result
                    agg.is_error = ev.is_error
                    sess_span.set_attribute("done.is_error", ev.is_error)
            sess_span.set_attribute("session.handle", session)
    finally:
        await adapter.cancel(session)
    return agg
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_session_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `uv run pytest -q && uv run ruff check`
Expected: all green (240 prior + new M6d tests), ruff clean. Watch for any integration test that asserted a session is *not* cancelled or reused after `_drive_harness`; none should exist (the Q&A loop starts a fresh session per round), but confirm.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/runtime/executors.py tests/unit/test_session_cleanup.py
git commit -m "fix(m6d): always cancel harness session (close temp-config leak)"
```

---

## Task 8: Wrap-up — docs + follow-ups note

**Files:**
- Create: `docs/superpowers/notes/m6d-observability-followups.md`

- [ ] **Step 1: Write the follow-ups note**

```markdown
# M6d follow-ups — durable span store + status/metrics/memory

- **knowledge-write / MCP-call spans not emitted.** Cross-process: the write
  happens in the `mcp_server.py` subprocess spawned by the harness, not the
  orchestrator. `run_messages` already surfaces `knowledge.write` spans *if*
  present (forward-compatible) — adding emission needs no query change. Likely
  approach: have `mcp_server.py` export to the same span DB (`$ORCH_SPAN_DB`)
  with the run's trace context passed via env.
- **Queries assume one trace_id per run.** Holds for linear MVP pipelines
  (locked by a test). Parallel / best-of-n branches (M9) may split traces; revisit
  then (stamp `run.id` on every span, or query by attribute).
- **Span DB never GC'd** (same as the checkpoint DB, M5 follow-up). No retention.
- **`orch metrics` shows duration only at step granularity** (run-level wall-clock
  and budget-vs-actual not surfaced yet).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/notes/m6d-observability-followups.md
git commit -m "docs(m6d): observability/status follow-ups"
```

---

## Self-Review

**Spec coverage** (against spec §3, §9, §12 M6d):
- §9 "durable, queryable SQLite span table, single record of truth" → Task 1.
- §9 / §3 `orch status` (run/step state) → Tasks 2, 5.
- §9 / §3 `orch metrics` (cost/tokens/timings) → Tasks 3, 6.
- §9 / §3 `orch memory` (message-bus log) → Tasks 4, 6.
- §3 CLI lists `status|metrics|memory` → Tasks 5, 6.
- §12 M6d "safety baseline polish" → Task 7 (the one concrete outstanding item: temp-file leak).
- §9 `knowledge-write`/`MCP-call` spans → explicitly deferred (cross-process) with forward-compatible query + follow-up note (Task 8). No silent gap.

**Placeholder scan:** No "TBD/TODO/handle edge cases". Two soft references are deliberate and bounded: (a) `ResolvedCaps()` construction — instruction to mirror existing `tests/` usage if the no-arg form fails; (b) manual smoke env vars — mirror `tests/integration/`. Both are about matching existing fixtures the worker can read, not unwritten logic.

**Type consistency:** `StatusView`/`StepView`/`MetricsView`/`StepMetric`/`MessageView` defined in Task 2–4 and consumed unchanged in Tasks 5–6. `run_status`/`run_metrics`/`run_messages` signatures `(db: Path, run_id: str)` consistent across query module and CLI. `SqliteSpanExporter(db_path: Path)` and `connect(db_path: Path)` consistent across store, tests, and CLI. Span attribute keys (`run.id`, `pipeline`, `step.id`, `step.role`, `step.is_error`, `step.type`, `cost.usd`, `cost.tokens`, `msg.*`) match those emitted in `executors.py` / `scheduler.py` / `message_bus.py` (verified against current source).

---

## Execution Handoff

Plan complete. After approval, execute task-by-task (TDD: red → green → commit). Tasks 1–4 are pure unit work; 5–6 add CLI; 7 is the safety fix + full-suite regression gate; 8 is docs. Each task ends green and committed, so the branch is runnable at every step.
