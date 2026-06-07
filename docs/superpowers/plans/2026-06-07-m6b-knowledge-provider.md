# M6b — Knowledge Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the knowledge provider (spec §8): **core injection** (always-loaded files written into a session's working dir), **on-demand lexical search** exposed to the harness as an MCP tool (`mcp__knowledge__search`), and **auditor-gated write** (`mcp__knowledge__write`) — closing the loop where `audit` writes durable lessons that the next run reads.

**Architecture:** A standalone, dependency-free **stdio MCP server** (`orchestrator/knowledge/mcp_server.py`) exposes `search` (lexical, over configured source globs) and — only when its config grants write — `write` (appends to `.orchestrator/knowledge/lessons.md` at the repo root, *outside* the discarded worktree so it persists). The **provider** (`provider.py`) does two jobs: (1) `inject_core` copies `knowledge/core.yaml`'s `inject` files into the agent's worktree; (2) `build_knowledge_mcp` turns a role's resolved `knowledge_read`/`knowledge_write` caps into an `McpServer` descriptor (deny-wins gating happens here — the write tool is only configured for roles granted write). Adapters translate `mcp_servers` into harness MCP config written *outside* the worktree (no diff pollution), mirroring the M6a `OPENCODE_CONFIG` pattern. `run_agent_step` wires it together: inject core → build the gated MCP server from caps → drive the harness → exclude injected core paths from the captured diff.

**Tech Stack:** Python 3.11, async subprocess, Pydantic v2, Typer, pytest-asyncio. MCP = hand-rolled newline-delimited JSON-RPC 2.0 over stdio (no SDK dependency — the fake harness/fakes define the contract, real-harness MCP reconciliation is a documented follow-up, mirroring how the real `claude`/`opencode` binaries were deferred). Package manager: **uv** (`uv run --extra dev python -m pytest`, `uv run --extra dev ruff check .`). NEVER system pip.

**This is M6b — the second M6 sub-milestone.** M6a shipped the OpenCode adapter + `HarnessRegistry`. M6b is the knowledge provider ONLY. No orchestrator-agent, no `orch status`, no safety-polish work here (those are M6c+).

## Grounding facts (verified against the current tree before writing this plan)

- `ResolvedCaps` (`orchestrator/safety/capabilities.py`) **already carries** `knowledge_read: tuple[str,...]` and `knowledge_write: tuple[str,...]`, resolved with deny-wins and "write is never in a preset, only an explicit per-source grant" (lines 42–43, 111–117, 131–132). M6b **consumes** these — it does not change resolution.
- `Workspace` (`orchestrator/config/loader.py`) holds `core_knowledge: CoreKnowledge | None` (`inject: list[str]`) and `knowledge_sources: dict[str, KnowledgeSource]` (each `sources: list[str]`, `backend: str = "lexical"`). The loader already validates that role `knowledge`/`access.knowledge` references resolve to known sources.
- The integration seam is `_drive_harness` in `orchestrator/runtime/executors.py:92`, which today hardcodes `mcp_servers=[]`. `run_agent_step` (line 119) creates the worktree (line 143) and captures the diff via `_capture_diff(cwd)` (line 48).
- `McpServer` (`orchestrator/harness/adapter.py`): `@dataclass(frozen=True)` with `name: str`, `command: str`, `args: list[str]`, `env: dict[str,str]`. Both adapters accept `mcp_servers` in `start_session` and store it but currently **ignore** it.
- The Claude adapter builds its command in `prompt`/`translate` (`claude_code.py:127–197`); MCP slots in as `--mcp-config <path>` + allowing `mcp__<server>` tools. The OpenCode adapter already writes a JSON config file pointed at by `OPENCODE_CONFIG` (`opencode.py` `start_session`); MCP servers fold into that JSON under an `mcp` key.
- Fake-binary test convention: `tests/fixtures/fake_harness/fake_harness.py` records argv to `$ORCH_FAKE_ARGV`; `tests/fixtures/fake_opencode/fake_opencode.py` records the seen `OPENCODE_CONFIG` path to `$ORCH_OC_CONFIG_SEEN`. M6b reuses both — no fake-binary changes needed.
- Example knowledge already exists: `examples/feature-pipeline/.orchestrator/knowledge/{core.yaml,lessons.yaml,repo-conventions.yaml}` and `roles/auditor.yaml` is referenced by `full.yaml` — confirm/extend, don't recreate blindly.

> **Real-vs-fake note (mirrors M6a):** M6b is built and tested against the existing fake harnesses (zero API cost). A fake harness emits canned NDJSON and does NOT actually open an MCP connection, so the end-to-end "agent calls `mcp__knowledge__search`" path is proven as the *sum* of unit tests (server speaks MCP correctly + provider builds the right descriptor + adapter passes the right config) rather than one fake-harness e2e. Reconciling the MCP wire format against the real `claude`/`opencode` binaries is a documented follow-up.

---

## File Structure

- `orchestrator/knowledge/__init__.py` (NEW) — empty package marker.
- `orchestrator/knowledge/lexical.py` (NEW) — `SearchResult` + pure `search(query, sources, root, limit)` lexical engine.
- `orchestrator/knowledge/mcp_server.py` (NEW) — `handle_request` (pure JSON-RPC dispatch), `ServerState`, and a `main()` stdio loop reading config from env (`ORCH_KB_*`). Exposes `search` always; `write` only when a write target is configured.
- `orchestrator/knowledge/provider.py` (NEW) — `inject_core(core, root, dest)` and `build_knowledge_mcp(workspace, caps, root)`.
- `orchestrator/runtime/executors.py` (MODIFY) — `_drive_harness` accepts `mcp_servers`; `run_agent_step` injects core, builds the gated MCP server, excludes injected paths from the diff; `_capture_diff` gains an `exclude` param.
- `orchestrator/harness/claude_code.py` (MODIFY) — translate `mcp_servers` → `--mcp-config <tempfile>` + allow `mcp__<name>` tools.
- `orchestrator/harness/opencode.py` (MODIFY) — fold `mcp_servers` into the `OPENCODE_CONFIG` JSON under `mcp`.
- `examples/feature-pipeline/.orchestrator/roles/auditor.yaml` (CONFIRM/EXTEND) — the only role with `access.knowledge.write: [lessons]`.
- Tests (NEW): `tests/unit/test_lexical.py`, `tests/unit/test_kb_mcp_server.py`, `tests/integration/test_kb_mcp_stdio.py`, `tests/unit/test_kb_provider.py`, `tests/integration/test_claude_mcp_wiring.py`, `tests/integration/test_opencode_mcp_wiring.py`, `tests/integration/test_knowledge_in_agent_step.py`, `tests/integration/test_knowledge_closed_loop.py`.
- `docs/superpowers/notes/m6b-knowledge-followups.md` (NEW).

---

## Task 1: Lexical search engine (pure)

**Files:**
- Create: `orchestrator/knowledge/__init__.py` (empty)
- Create: `orchestrator/knowledge/lexical.py`
- Test: `tests/unit/test_lexical.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_lexical.py
from orchestrator.knowledge.lexical import SearchResult, search


def _make_repo(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text(
        "Worktrees isolate each agent.\nNever push to main directly.\n"
    )
    (tmp_path / "docs" / "b.md").write_text("Unrelated content about widgets.\n")
    (tmp_path / "notes.txt").write_text("worktree cleanup happens on success.\n")
    return tmp_path


def test_finds_matching_lines_case_insensitive(tmp_path):
    root = _make_repo(tmp_path)
    results = search("WORKTREE", ["docs/**", "*.txt"], root, limit=10)
    paths = {r.path for r in results}
    assert "docs/a.md" in paths
    assert "notes.txt" in paths
    assert "docs/b.md" not in paths


def test_result_carries_path_line_and_snippet(tmp_path):
    root = _make_repo(tmp_path)
    [hit] = [r for r in search("push to main", ["docs/**"], root, limit=10)
             if r.path == "docs/a.md"]
    assert isinstance(hit, SearchResult)
    assert hit.line == 2
    assert "push to main" in hit.snippet.lower()


def test_ranking_prefers_more_term_hits(tmp_path):
    root = tmp_path
    (root / "many.md").write_text("agent agent agent worktree\n")
    (root / "few.md").write_text("agent once\n")
    results = search("agent worktree", ["*.md"], root, limit=10)
    assert results[0].path == "many.md"


def test_limit_caps_results(tmp_path):
    root = tmp_path
    for i in range(5):
        (root / f"f{i}.md").write_text("match here\n")
    assert len(search("match", ["*.md"], root, limit=3)) == 3


def test_no_match_returns_empty(tmp_path):
    (tmp_path / "x.md").write_text("nothing relevant\n")
    assert search("zzz", ["*.md"], tmp_path, limit=10) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_lexical.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.knowledge.lexical`).

- [ ] **Step 3: Implement**

Create `orchestrator/knowledge/__init__.py` (empty). Create `orchestrator/knowledge/lexical.py`:

```python
"""Lexical knowledge search (spec §8, no embeddings in MVP).

Pure file search over a set of glob `sources` rooted at a repo. Term-frequency
ranked; deterministic. Backs the MCP `search` tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchResult:
    path: str  # repo-relative
    line: int  # 1-based
    snippet: str
    score: int


def _iter_files(sources: list[str], root: Path) -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in sources:
        for p in sorted(root.glob(pattern)):
            if p.is_file():
                seen.setdefault(p, None)
    return list(seen)


def search(query: str, sources: list[str], root: Path, *, limit: int = 10) -> list[SearchResult]:
    """Return term-frequency-ranked line matches for `query` across `sources`."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    results: list[SearchResult] = []
    for path in _iter_files(sources, root):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        for lineno, raw in enumerate(text.splitlines(), start=1):
            low = raw.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                results.append(SearchResult(rel, lineno, raw.strip(), score))
    results.sort(key=lambda r: (-r.score, r.path, r.line))
    return results[:limit]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_lexical.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/knowledge/__init__.py orchestrator/knowledge/lexical.py tests/unit/test_lexical.py
git commit -m "feat(m6b): lexical knowledge search engine (pure, term-frequency ranked)"
```

---

## Task 2: MCP server request handler (pure JSON-RPC dispatch)

**Files:**
- Create: `orchestrator/knowledge/mcp_server.py` (handler + state only this task)
- Test: `tests/unit/test_kb_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_mcp_server.py
from orchestrator.knowledge.mcp_server import ServerState, handle_request


def _state(tmp_path, write=False):
    (tmp_path / "kb.md").write_text("lesson: always rebase before merge\n")
    target = tmp_path / "lessons.md" if write else None
    return ServerState(sources=["*.md"], root=tmp_path, write_target=target)


def test_initialize_advertises_tools(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _state(tmp_path)
    )
    assert resp["id"] == 1
    assert resp["result"]["capabilities"]["tools"] == {}
    assert resp["result"]["serverInfo"]["name"] == "knowledge"


def test_initialized_notification_returns_none(tmp_path):
    assert handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, _state(tmp_path)
    ) is None


def test_tools_list_search_only_without_write(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, _state(tmp_path, write=False)
    )
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"search"}


def test_tools_list_includes_write_when_granted(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, _state(tmp_path, write=True)
    )
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"search", "write"}


def test_call_search_returns_text_content(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "search", "arguments": {"query": "rebase"}}},
        _state(tmp_path),
    )
    block = resp["result"]["content"][0]
    assert block["type"] == "text"
    assert "rebase" in block["text"].lower()
    assert resp["result"]["isError"] is False


def test_call_write_appends_to_target(tmp_path):
    st = _state(tmp_path, write=True)
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "write", "arguments": {"lesson": "prefer 3way apply"}}},
        st,
    )
    assert resp["result"]["isError"] is False
    assert "prefer 3way apply" in st.write_target.read_text()


def test_call_write_refused_when_not_granted(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "write", "arguments": {"lesson": "x"}}},
        _state(tmp_path, write=False),
    )
    assert resp["result"]["isError"] is True


def test_unknown_method_returns_error(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "bogus/method"}, _state(tmp_path)
    )
    assert resp["error"]["code"] == -32601
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_kb_mcp_server.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.knowledge.mcp_server`).

- [ ] **Step 3: Implement the handler**

Create `orchestrator/knowledge/mcp_server.py`:

```python
"""Knowledge MCP server (spec §8): stdio JSON-RPC 2.0, newline-delimited.

Exposes `search` (lexical, always) and `write` (append a durable lesson, ONLY
when a write target is configured — deny-wins gating is enforced by the provider
that constructs this server's config). Hand-rolled (no MCP SDK dep); the fake
harnesses define the contract, real-harness reconciliation is a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.knowledge.lexical import search

PROTOCOL_VERSION = "2024-11-05"


@dataclass
class ServerState:
    sources: list[str]
    root: Path
    write_target: Path | None = None  # None → write tool not offered


def _tools(state: ServerState) -> list[dict]:
    tools = [
        {
            "name": "search",
            "description": "Lexical search over the project's knowledge sources.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    if state.write_target is not None:
        tools.append({
            "name": "write",
            "description": "Append a durable lesson to the knowledge base.",
            "inputSchema": {
                "type": "object",
                "properties": {"lesson": {"type": "string"}},
                "required": ["lesson"],
            },
        })
    return tools


def _ok(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _do_search(state: ServerState, args: dict) -> dict:
    hits = search(str(args.get("query", "")), state.sources, state.root, limit=10)
    if not hits:
        return _text("No matching knowledge found.")
    lines = [f"{h.path}:{h.line}: {h.snippet}" for h in hits]
    return _text("\n".join(lines))


def _do_write(state: ServerState, args: dict) -> dict:
    if state.write_target is None:
        return _text("write not permitted for this role", is_error=True)
    lesson = str(args.get("lesson", "")).strip()
    if not lesson:
        return _text("empty lesson", is_error=True)
    state.write_target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with state.write_target.open("a") as fh:
        fh.write(f"- ({stamp}) {lesson}\n")
    return _text(f"recorded lesson to {state.write_target.name}")


def handle_request(req: dict, state: ServerState) -> dict | None:
    """Dispatch one JSON-RPC request. Returns None for notifications."""
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "knowledge", "version": "0.1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": _tools(state)})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "search":
            return _ok(req_id, _do_search(state, args))
        if name == "write":
            return _ok(req_id, _do_write(state, args))
        return _ok(req_id, _text(f"unknown tool '{name}'", is_error=True))
    return _err(req_id, -32601, f"method not found: {method}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_kb_mcp_server.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/knowledge/mcp_server.py tests/unit/test_kb_mcp_server.py
git commit -m "feat(m6b): knowledge MCP request handler (search + gated write, JSON-RPC dispatch)"
```

---

## Task 3: MCP server stdio loop + env config (spawnable)

**Files:**
- Modify: `orchestrator/knowledge/mcp_server.py` (add `state_from_env` + `main`)
- Test: `tests/integration/test_kb_mcp_stdio.py`

- [ ] **Step 1: Write the failing test** (spawn the module as a subprocess, speak newline-delimited JSON-RPC)

```python
# tests/integration/test_kb_mcp_stdio.py
import json
import subprocess
import sys
from pathlib import Path


def _rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _read(proc):
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else None


def _spawn(tmp_path, env_extra):
    (tmp_path / "kb.md").write_text("lesson: drain stderr before wiring real binary\n")
    env = {
        "ORCH_KB_SOURCES": json.dumps(["*.md"]),
        "ORCH_KB_ROOT": str(tmp_path),
        **env_extra,
    }
    import os
    full_env = {**os.environ, **env}
    return subprocess.Popen(
        [sys.executable, "-m", "orchestrator.knowledge.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=full_env,
        cwd=str(Path(__file__).parents[2]),
    )


def test_stdio_initialize_and_search(tmp_path):
    proc = _spawn(tmp_path, {})
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert _read(proc)["result"]["serverInfo"]["name"] == "knowledge"
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})  # no reply
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "search", "arguments": {"query": "drain stderr"}}})
        out = _read(proc)["result"]["content"][0]["text"]
        assert "drain stderr" in out.lower()
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_stdio_write_persists_to_target(tmp_path):
    target = tmp_path / "lessons.md"
    proc = _spawn(tmp_path, {"ORCH_KB_WRITE_TARGET": str(target)})
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "write", "arguments": {"lesson": "pin protocol version"}}})
        assert _read(proc)["result"]["isError"] is False
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
    assert "pin protocol version" in target.read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_kb_mcp_stdio.py -v`
Expected: FAIL (no `__main__` / `main` in the module → subprocess errors, assertions fail).

- [ ] **Step 3: Implement the stdio loop**

Append to `orchestrator/knowledge/mcp_server.py`:

```python
import json
import os
import sys


def state_from_env() -> ServerState:
    sources = json.loads(os.environ.get("ORCH_KB_SOURCES", "[]"))
    root = Path(os.environ.get("ORCH_KB_ROOT", "."))
    wt = os.environ.get("ORCH_KB_WRITE_TARGET")
    return ServerState(sources=sources, root=root, write_target=Path(wt) if wt else None)


def main() -> int:
    state = state_from_env()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req, state)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_kb_mcp_stdio.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/knowledge/mcp_server.py tests/integration/test_kb_mcp_stdio.py
git commit -m "feat(m6b): knowledge MCP stdio loop + env config (spawnable server)"
```

---

## Task 4: Provider — core injection

**Files:**
- Create: `orchestrator/knowledge/provider.py` (`inject_core` only this task)
- Test: `tests/unit/test_kb_provider.py` (core-injection cases)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kb_provider.py
from orchestrator.config.schemas import CoreKnowledge
from orchestrator.knowledge.provider import inject_core


def test_injects_files_into_dest(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    (root / "AGENTS.md").write_text("be careful\n")
    (root / "docs").mkdir()
    (root / "docs" / "arch.md").write_text("layers\n")
    dest = tmp_path / "wt"; dest.mkdir()

    injected = inject_core(CoreKnowledge(inject=["AGENTS.md", "docs/arch.md"]), root, dest)

    assert injected == ["AGENTS.md", "docs/arch.md"]
    assert (dest / "AGENTS.md").read_text() == "be careful\n"
    assert (dest / "docs" / "arch.md").read_text() == "layers\n"


def test_missing_source_is_skipped(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    (root / "AGENTS.md").write_text("x\n")
    dest = tmp_path / "wt"; dest.mkdir()
    injected = inject_core(CoreKnowledge(inject=["AGENTS.md", "nope.md"]), root, dest)
    assert injected == ["AGENTS.md"]
    assert not (dest / "nope.md").exists()


def test_none_core_injects_nothing(tmp_path):
    dest = tmp_path / "wt"; dest.mkdir()
    assert inject_core(None, tmp_path, dest) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_kb_provider.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.knowledge.provider`).

- [ ] **Step 3: Implement**

Create `orchestrator/knowledge/provider.py`:

```python
"""Knowledge provider (spec §8): core injection + on-demand MCP wiring.

Two jobs, both consumed by `run_agent_step`:
- `inject_core`: copy core.yaml `inject` files into the agent's worktree so the
  harness reads them (AGENTS.md + pinned docs). Always read, never writable.
- `build_knowledge_mcp`: turn a role's resolved knowledge caps into an McpServer
  descriptor. Deny-wins write gating lives HERE — the write target (and thus the
  `write` tool) is only configured for roles granted write.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from orchestrator.config.schemas import CoreKnowledge


def inject_core(core: CoreKnowledge | None, root: Path, dest: Path) -> list[str]:
    """Copy each `inject` file from `root` into `dest`. Returns injected rel paths."""
    if core is None:
        return []
    injected: list[str] = []
    for rel in core.inject:
        src = root / rel
        if not src.is_file():
            continue  # missing source: skip (validated softly; not fatal in MVP)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        injected.append(rel)
    return injected
```

(The `json`, `sys` imports and `build_knowledge_mcp` land in Task 5 — leave them out here to keep ruff clean. **IMPLEMENTER NOTE:** do not add the `json`/`sys` imports until Task 5 needs them, or ruff F401 will fail this commit.)

Correction for THIS task — the import block should be only what `inject_core` uses:

```python
from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator.config.schemas import CoreKnowledge
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_kb_provider.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/knowledge/provider.py tests/unit/test_kb_provider.py
git commit -m "feat(m6b): provider core injection — copy inject files into the worktree"
```

---

## Task 5: Provider — build the gated MCP server descriptor

**Files:**
- Modify: `orchestrator/knowledge/provider.py` (add `build_knowledge_mcp`)
- Test: `tests/unit/test_kb_provider.py` (extend with MCP-descriptor cases)

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_kb_provider.py`)

```python
# --- append to tests/unit/test_kb_provider.py ---
import json
import sys

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import KnowledgeSource
from orchestrator.knowledge.provider import build_knowledge_mcp
from orchestrator.safety.capabilities import ResolvedCaps


def _ws():
    ws = Workspace(config=__import__("orchestrator.config.schemas", fromlist=["Config"]).Config())
    ws.knowledge_sources = {
        "repo-conventions": KnowledgeSource(name="repo-conventions", sources=["docs/**"]),
        "lessons": KnowledgeSource(name="lessons", sources=[".orchestrator/knowledge/lessons.md"]),
    }
    return ws


def test_no_grants_yields_no_server(tmp_path):
    caps = ResolvedCaps()  # no knowledge_read / knowledge_write
    assert build_knowledge_mcp(_ws(), caps, tmp_path) == []


def test_read_grant_builds_search_only_server(tmp_path):
    caps = ResolvedCaps(knowledge_read=("repo-conventions",))
    [srv] = build_knowledge_mcp(_ws(), caps, tmp_path)
    assert srv.name == "knowledge"
    assert srv.command == sys.executable
    assert srv.args == ["-m", "orchestrator.knowledge.mcp_server"]
    assert json.loads(srv.env["ORCH_KB_SOURCES"]) == ["docs/**"]
    assert srv.env["ORCH_KB_ROOT"] == str(tmp_path)
    assert "ORCH_KB_WRITE_TARGET" not in srv.env  # read-only → no write tool


def test_write_grant_sets_write_target(tmp_path):
    caps = ResolvedCaps(knowledge_read=("lessons",), knowledge_write=("lessons",))
    [srv] = build_knowledge_mcp(_ws(), caps, tmp_path)
    assert srv.env["ORCH_KB_WRITE_TARGET"] == str(tmp_path / ".orchestrator/knowledge/lessons.md")


def test_multiple_read_sources_merge_globs(tmp_path):
    caps = ResolvedCaps(knowledge_read=("repo-conventions", "lessons"))
    [srv] = build_knowledge_mcp(_ws(), caps, tmp_path)
    assert json.loads(srv.env["ORCH_KB_SOURCES"]) == ["docs/**", ".orchestrator/knowledge/lessons.md"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_kb_provider.py -v`
Expected: FAIL (`build_knowledge_mcp` missing).

- [ ] **Step 3: Implement**

Add to `orchestrator/knowledge/provider.py` (extend the import block to add `json`, `sys`, and the typing imports shown):

```python
import json
import sys

from orchestrator.config.loader import Workspace
from orchestrator.harness.adapter import McpServer
from orchestrator.safety.capabilities import ResolvedCaps


def build_knowledge_mcp(
    workspace: Workspace, caps: ResolvedCaps, root: Path
) -> list[McpServer]:
    """ResolvedCaps knowledge grants → an McpServer (or none). Deny-wins gating:
    the write target is set ONLY when `caps.knowledge_write` is non-empty."""
    if not caps.knowledge_read and not caps.knowledge_write:
        return []

    sources: list[str] = []
    for name in caps.knowledge_read:
        src = workspace.knowledge_sources.get(name)
        if src is not None:
            sources.extend(src.sources)

    env: dict[str, str] = {
        "ORCH_KB_SOURCES": json.dumps(_dedup(sources)),
        "ORCH_KB_ROOT": str(root),
    }
    if caps.knowledge_write:
        # MVP: write appends to the first granted writable source (spec §8 -> lessons.md).
        first = caps.knowledge_write[0]
        wsrc = workspace.knowledge_sources.get(first)
        target_rel = (wsrc.sources[0] if wsrc and wsrc.sources
                      else ".orchestrator/knowledge/lessons.md")
        env["ORCH_KB_WRITE_TARGET"] = str(root / target_rel)

    return [McpServer(
        name="knowledge",
        command=sys.executable,
        args=["-m", "orchestrator.knowledge.mcp_server"],
        env=env,
    )]


def _dedup(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for i in items:
        seen.setdefault(i, None)
    return list(seen)
```

> IMPLEMENTER NOTE: `McpServer.env` and `args` are mutable defaults on a frozen dataclass — pass fresh `dict`/`list` instances (as above), never share. Confirm `McpServer` field names against `orchestrator/harness/adapter.py` before finalizing.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_kb_provider.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/knowledge/provider.py tests/unit/test_kb_provider.py
git commit -m "feat(m6b): provider builds gated knowledge McpServer from resolved caps"
```

---

## Task 6: Claude adapter — translate mcp_servers → --mcp-config + allow tools

**Files:**
- Modify: `orchestrator/harness/claude_code.py`
- Test: `tests/integration/test_claude_mcp_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_claude_mcp_wiring.py
import json
import sys
from pathlib import Path

from orchestrator.harness.adapter import McpServer
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, servers):
    session = await adapter.start_session(
        cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=servers
    )
    stream = await adapter.prompt(session, "go")
    async for _ in stream:
        pass
    return session


async def test_mcp_config_passed_and_tools_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    server = McpServer(name="knowledge", command=sys.executable,
                       args=["-m", "orchestrator.knowledge.mcp_server"],
                       env={"ORCH_KB_SOURCES": "[]", "ORCH_KB_ROOT": str(tmp_path)})
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [server])

    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "--mcp-config" in argv
    cfg_path = argv[argv.index("--mcp-config") + 1]
    cfg = json.loads(Path(cfg_path).read_text())
    assert cfg["mcpServers"]["knowledge"]["command"] == sys.executable
    # the MCP tools are allow-listed so the harness may call them
    allowed = argv[argv.index("--allowedTools") + 1]
    assert "mcp__knowledge" in allowed
    # config lives OUTSIDE the worktree (no diff pollution)
    assert str(tmp_path) not in cfg_path or "tmp" in cfg_path.lower()


async def test_no_servers_no_mcp_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [])
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "--mcp-config" not in argv
```

> IMPLEMENTER NOTE: confirm `tests/fixtures/fake_harness/scripts/plan.ndjson` exists (it does — used since M2). If the fake needs a `Done`/result event to terminate cleanly, `plan.ndjson` already provides it.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_claude_mcp_wiring.py -v`
Expected: FAIL (`--mcp-config` absent — adapter ignores `mcp_servers`).

- [ ] **Step 3: Implement**

In `orchestrator/harness/claude_code.py`:

- Add imports near the top: `import json`, `import os`, `import tempfile` (check which already exist — `asyncio`, `json`, `uuid` are likely present; add only the missing ones).
- Add a module-level helper:

```python
def _write_mcp_config(servers: list[McpServer]) -> str:
    """Write a Claude `--mcp-config` JSON to a temp file OUTSIDE the worktree."""
    cfg = {
        "mcpServers": {
            s.name: {"command": s.command, "args": list(s.args), "env": dict(s.env)}
            for s in servers
        }
    }
    fd, path = tempfile.mkstemp(prefix="orch-mcp-", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh)
    return path
```

- In `prompt`, after building `flags`, append MCP wiring when the session has servers:

```python
    async def prompt(self, session, text, *, output_schema=None):
        sess = self._sessions[session]
        flags = self.translate(sess.caps, cwd=sess.cwd)
        if sess.mcp_servers:
            cfg_path = _write_mcp_config(sess.mcp_servers)
            sess.mcp_config_path = cfg_path
            flags += ["--mcp-config", cfg_path]
            # allow the harness to call each server's tools (mcp__<server>)
            mcp_tools = ",".join(f"mcp__{s.name}" for s in sess.mcp_servers)
            flags += ["--allowedTools", mcp_tools]
        cmd = [*self._binary, "-p", text, "--output-format", "stream-json", *flags]
        return self._stream(session, cmd)
```

> IMPLEMENTER NOTE: `translate()` already emits one `--allowedTools` from caps. Two `--allowedTools` flags is the simplest correct approach IF the real CLI merges repeats; to be safe and match the test (which reads `argv.index("--allowedTools")` — the FIRST occurrence), prefer MERGING instead: have `prompt` compute the full allowed-tools list and let `translate` skip it, OR append the mcp tools to the caps tools before the single flag. RECOMMENDED: add an optional `extra_allowed_tools` param to `translate(caps, *, cwd, extra_allowed_tools=())` and have it fold them into the single `--allowedTools` value. Update the test's `argv.index("--allowedTools")` lookup to find `mcp__knowledge` within that single value (the test already asserts `"mcp__knowledge" in allowed`, which works for a merged value). Pick the merged approach to avoid duplicate flags.

- Add `mcp_config_path: str | None = None` to the `_Session` dataclass, and unlink it in `cancel` (best-effort `os.unlink`, ignore `OSError`).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_claude_mcp_wiring.py -v`
Then the adapter contract suite to confirm no regression: `uv run --extra dev python -m pytest tests/integration/test_adapter_contract.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/harness/claude_code.py tests/integration/test_claude_mcp_wiring.py
git commit -m "feat(m6b): Claude adapter wires mcp_servers → --mcp-config + allow mcp tools"
```

---

## Task 7: OpenCode adapter — fold mcp_servers into OPENCODE_CONFIG

**Files:**
- Modify: `orchestrator/harness/opencode.py`
- Test: `tests/integration/test_opencode_mcp_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_opencode_mcp_wiring.py
import json
import sys
from pathlib import Path

from orchestrator.harness.adapter import McpServer
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, servers):
    session = await adapter.start_session(
        cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=servers
    )
    stream = await adapter.prompt(session, "go")
    async for _ in stream:
        pass


async def test_mcp_servers_in_opencode_config(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_CONFIG_SEEN", str(tmp_path / "cfgpath.txt"))
    server = McpServer(name="knowledge", command=sys.executable,
                       args=["-m", "orchestrator.knowledge.mcp_server"],
                       env={"ORCH_KB_SOURCES": "[]", "ORCH_KB_ROOT": str(tmp_path)})
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [server])

    cfg_path = (tmp_path / "cfgpath.txt").read_text().strip()
    cfg = json.loads(Path(cfg_path).read_text())
    mcp = cfg["mcp"]["knowledge"]
    assert mcp["type"] == "local"
    assert mcp["command"] == [sys.executable, "-m", "orchestrator.knowledge.mcp_server"]
    assert mcp["enabled"] is True


async def test_no_servers_no_mcp_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_CONFIG_SEEN", str(tmp_path / "cfgpath.txt"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [])
    cfg = json.loads(Path((tmp_path / "cfgpath.txt").read_text().strip()).read_text())
    assert "mcp" not in cfg or cfg["mcp"] == {}
```

> IMPLEMENTER NOTE: OpenCode's config `mcp` schema (per its docs) uses `{"type": "local", "command": [...], "environment": {...}, "enabled": true}`. Field names (`command` as a list incl. the binary; `environment` vs `env`) are not 100% pinned — write them per the docs above and add to the M6b reconciliation follow-up. The test pins the shape this adapter emits; reconciliation against the real binary is deferred (mirrors M6a).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_opencode_mcp_wiring.py -v`
Expected: FAIL (`mcp` key absent — adapter ignores `mcp_servers`).

- [ ] **Step 3: Implement**

In `orchestrator/harness/opencode.py`, in `start_session`, after building `cfg = build_permission_config(caps)`, fold in MCP servers BEFORE writing the temp config:

```python
        cfg = build_permission_config(caps)
        if mcp_servers:
            cfg["mcp"] = {
                s.name: {
                    "type": "local",
                    "command": [s.command, *s.args],
                    "environment": dict(s.env),
                    "enabled": True,
                }
                for s in mcp_servers
            }
        fd, path = tempfile.mkstemp(prefix="orch-oc-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg, fh)
```

(The temp config is already written outside the worktree and unlinked in `cancel` — no diff pollution. `mcp_servers` is already a parameter of `start_session`; it was previously stored but unused.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_opencode_mcp_wiring.py -v`
Then: `uv run --extra dev python -m pytest tests/integration/test_opencode_adapter.py -v` (no regression).
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/harness/opencode.py tests/integration/test_opencode_mcp_wiring.py
git commit -m "feat(m6b): OpenCode adapter folds mcp_servers into OPENCODE_CONFIG"
```

---

## Task 8: Wire the provider into the agent executor

**Files:**
- Modify: `orchestrator/runtime/executors.py`
- Test: `tests/integration/test_knowledge_in_agent_step.py`

- [ ] **Step 1: Write the failing test** (an agent step on a role with knowledge read → the harness gets `--mcp-config`; an injected core file lands in the worktree but is excluded from the diff)

```python
# tests/integration/test_knowledge_in_agent_step.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import (
    Access, Config, CoreKnowledge, Harness, KnowledgeAccess, KnowledgeSource,
    Pipeline, Role, Step, StepType,
)
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    # uncommitted core file at repo root (so it is NOT already in a worktree off base)
    (repo / "AGENTS.md").write_text("project rules\n")
    return repo


def _ws():
    ws = Workspace(config=Config())
    ws.core_knowledge = CoreKnowledge(inject=["AGENTS.md"])
    ws.knowledge_sources = {"repo-conventions": KnowledgeSource(
        name="repo-conventions", sources=["docs/**"])}
    ws.roles = {"impl": Role(
        name="impl", harness=Harness.claude_code,
        access=Access(knowledge=KnowledgeAccess(read=["repo-conventions"])),
    )}
    return ws


async def test_agent_step_gets_mcp_and_injects_core(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "implement.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    from orchestrator.runtime.executors import run_agent_step
    ws = _ws()
    repo = _repo(tmp_path)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", pipeline_name="p", inputs={"task": "x"})
    step = Step(id="implement", role="impl", type=StepType.agent, prompt="do {{task}}")
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter)
    # the harness was handed an MCP config (role has knowledge read)
    argv = (tmp_path / "argv.txt").read_text()
    assert "--mcp-config" in argv
    # the injected core file is NOT in the captured agent diff (core is never writable)
    assert "AGENTS.md" not in art.diff
```

> IMPLEMENTER NOTE: check `implement.ndjson` exists under the fake harness scripts (it is referenced by M-series tests). If absent, use `plan.ndjson`. Confirm `RunContext`'s constructor field names (`run_id`, `pipeline_name`, `inputs`) against `orchestrator/runtime/state.py` before finalizing the test.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_knowledge_in_agent_step.py -v`
Expected: FAIL (`--mcp-config` absent — `_drive_harness` still passes `mcp_servers=[]`).

- [ ] **Step 3: Implement**

In `orchestrator/runtime/executors.py`:

- Add imports: `from orchestrator.knowledge.provider import build_knowledge_mcp, inject_core`.
- Change `_capture_diff` to accept an exclude list:

```python
def _capture_diff(cwd: Path, exclude: tuple[str, ...] = ()) -> str:
    subprocess.run(["git", "add", "-A", "-N"], cwd=cwd, capture_output=True, text=True)
    pathspec = ["--", "."] + [f":(exclude){p}" for p in exclude] if exclude else []
    diff = subprocess.run(
        ["git", "diff", *pathspec], cwd=cwd, capture_output=True, text=True
    ).stdout
    subprocess.run(["git", "reset", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return diff
```

- Change `_drive_harness` signature to accept servers and pass them through:

```python
async def _drive_harness(adapter, caps, cwd, prompt, output_schema, tracer,
                         mcp_servers=()):
    agg = _Aggregate()
    session = await adapter.start_session(cwd=cwd, caps=caps, mcp_servers=list(mcp_servers))
    ...
```

(`run_task_step` calls `_drive_harness(...)` without `mcp_servers` — the default `()` keeps task steps unchanged.)

- In `run_agent_step`, after `caps = resolve_capabilities(role, workspace)` and after `worktree = create_worktree(...)`, inject core and build the MCP server:

```python
    injected = tuple(inject_core(workspace.core_knowledge, Path(repo), worktree.path))
    mcp_servers = build_knowledge_mcp(workspace, caps, Path(repo))
```

  Pass `mcp_servers=mcp_servers` into each `_drive_harness(...)` call inside the retry loop, and change the diff capture to `diff = _capture_diff(worktree.path, exclude=injected)`.

> IMPLEMENTER NOTE: the MCP **write target** (`ORCH_KB_WRITE_TARGET`) is built against `Path(repo)` (the real repo root), NOT `worktree.path` — so an auditor's durable lesson persists after the worktree is discarded (spec §8 closed loop). Core injection writes into `worktree.path` (the agent's cwd). Keep these two roots distinct.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_knowledge_in_agent_step.py -v`
Then the FULL suite (all prior agent/task/merge tests pass `mcp_servers` default `()` → unchanged): `uv run --extra dev python -m pytest -q`. Baseline before M6b was 190; expect prior tests green + the new ones.
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/executors.py tests/integration/test_knowledge_in_agent_step.py
git commit -m "feat(m6b): agent step injects core knowledge + wires gated MCP; core excluded from diff"
```

---

## Task 9: Closed-loop demo + auditor role + example compile

**Files:**
- Confirm/Modify: `examples/feature-pipeline/.orchestrator/roles/auditor.yaml`
- Test: `tests/integration/test_knowledge_closed_loop.py`
- Confirm: `tests/integration/test_example_compiles.py` still passes (no change expected)

- [ ] **Step 1: Confirm the auditor role grants knowledge write**

Read `examples/feature-pipeline/.orchestrator/roles/auditor.yaml`. Ensure it contains a knowledge **write** grant on `lessons` and **read** so its MCP server offers both tools. If missing, set:

```yaml
# The ONLY role with knowledge write access (spec §8): durable lessons.
harness: claude_code
permissions: read-only        # auditor reads code, writes only the KB
access:
  knowledge:
    read: [repo-conventions, lessons]
    write: [lessons]
```

> IMPLEMENTER NOTE: `permissions: read-only` zeroes filesystem/edit caps but `access.knowledge.write` is preserved by the resolver (write is an explicit per-source grant, never a preset — verified in `resolve_capabilities`). Confirm the example still loads: `uv run orch compile full --root examples/feature-pipeline/.orchestrator`.

- [ ] **Step 2: Write the closed-loop test** (provider → server → search sees what write wrote — the spec §8 loop, proven at the provider/server seam since the fake harness can't call MCP itself)

```python
# tests/integration/test_knowledge_closed_loop.py
import json
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, KnowledgeSource
from orchestrator.knowledge.provider import build_knowledge_mcp
from orchestrator.safety.capabilities import ResolvedCaps


def _ws():
    ws = Workspace(config=Config())
    ws.knowledge_sources = {
        "lessons": KnowledgeSource(name="lessons",
                                   sources=[".orchestrator/knowledge/lessons.md"]),
    }
    return ws


def _rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n"); proc.stdin.flush()


def _read(proc):
    return json.loads(proc.stdout.readline())


def test_audit_write_is_searchable_next_run(tmp_path):
    root = tmp_path
    (root / ".orchestrator" / "knowledge").mkdir(parents=True)

    # 1) Auditor caps (read+write) → server with the write tool.
    auditor_caps = ResolvedCaps(knowledge_read=("lessons",), knowledge_write=("lessons",))
    [wsrv] = build_knowledge_mcp(_ws(), auditor_caps, root)

    # 2) Auditor writes a durable lesson via the MCP write tool.
    import os
    env = {**os.environ, **wsrv.env}
    wp = subprocess.Popen([wsrv.command, *wsrv.args], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, env=env,
                          cwd=str(Path(__file__).parents[2]))
    try:
        _rpc(wp, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "write",
                             "arguments": {"lesson": "rebase agent worktrees off base"}}})
        assert _read(wp)["result"]["isError"] is False
    finally:
        wp.stdin.close(); wp.wait(timeout=5)

    # 3) Next run: a reader role (read only) searches and finds the lesson.
    reader_caps = ResolvedCaps(knowledge_read=("lessons",))
    [rsrv] = build_knowledge_mcp(_ws(), reader_caps, root)
    assert "ORCH_KB_WRITE_TARGET" not in rsrv.env  # reader cannot write
    renv = {**os.environ, **rsrv.env}
    rp = subprocess.Popen([rsrv.command, *rsrv.args], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, env=renv,
                          cwd=str(Path(__file__).parents[2]))
    try:
        _rpc(rp, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "search", "arguments": {"query": "rebase worktrees"}}})
        out = _read(rp)["result"]["content"][0]["text"]
        assert "rebase agent worktrees" in out
    finally:
        rp.stdin.close(); rp.wait(timeout=5)
```

- [ ] **Step 3: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_knowledge_closed_loop.py -v`
Then confirm the example compile test is still green: `uv run --extra dev python -m pytest tests/integration/test_example_compiles.py -v`
Expected: PASS.

- [ ] **Step 4: Manual CLI smoke (optional but recommended)**

Confirm the full example still runs end-to-end against the fakes (the `audit` step now resolves a write-enabled MCP server; the fake harness won't call it, but the run must still complete and the MCP config must be built without error):

`uv run orch run full --task "add a flag" --root examples/feature-pipeline/.orchestrator --repo <tmp-repo>` (with `ORCH_CLAUDE_BIN`/`ORCH_FAKE_SCRIPT_DIR` set to the fakes; pause→resume as in M5). Capture output for the follow-ups note.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add examples/feature-pipeline/.orchestrator/roles/auditor.yaml tests/integration/test_knowledge_closed_loop.py
git commit -m "feat(m6b): closed-loop demo — auditor write becomes next run's searchable knowledge"
```

---

## Task 10: M6b follow-ups note

**Files:**
- Create: `docs/superpowers/notes/m6b-knowledge-followups.md`

- [ ] **Step 1: Write the note** (mirror the structure of `docs/superpowers/notes/m6a-opencode-followups.md`)

Capture, with rationale:
- **What M6b shipped:** lexical search engine; a hand-rolled stdio MCP server (`search` always, `write` gated); provider (`inject_core` + `build_knowledge_mcp`); MCP wiring in both adapters (config written outside the worktree → no diff pollution); executor integration (core injected into the worktree and excluded from the captured diff; write target rooted at the real repo so lessons persist past the discarded worktree).
- **Headline risk — real-vs-fake MCP reconciliation:** the MCP wire format (Claude `--mcp-config` `mcpServers` shape; OpenCode config `mcp` shape — `type`/`command`-as-list/`environment` field names) and the harness's MCP tool-allow syntax (`mcp__<server>` vs `mcp__<server>__<tool>`) are written from docs and pinned by the fakes, NOT verified against the real binaries. Because a fake harness never opens an MCP connection, the e2e "agent calls `mcp__knowledge__search`" path is proven only as the sum of unit tests. Reconcile against real `claude`/`opencode` before relying on live retrieval.
- **MVP fidelity notes:** lexical search is term-frequency line matching (no embeddings — spec defers); write appends a one-line dated bullet to the first granted writable source (`lessons.md`); the MCP protocol implements only `initialize`/`initialized`/`ping`/`tools/list`/`tools/call` (enough for a tools-only server).
- **Deferred / out of M6b scope (not bugs):** task steps don't get knowledge MCP (read-only glue; could be added); `orch status` view of knowledge writes (M6c — write is recorded only as a file append today, the audit-log span is not yet emitted for MCP calls since the fake can't call them); MCP server process lifecycle/teardown is owned by the harness; no per-source read filtering inside the server beyond the granted globs; temp MCP/permission config files may leak in `$TMPDIR` on non-cancelled paths (acceptable for MVP, same as M6a).
- **Remaining M6 scope after M6b:** orchestrator agent (run-owner, message bus, worker Q&A); `orch status` (read checkpoints/spans incl. knowledge-write + MCP-call spans); safety baseline polish. (M6c+.)

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/notes/m6b-knowledge-followups.md
git commit -m "docs(m6b): knowledge provider follow-ups"
```

---

## Final Review (after all tasks)

Dispatch a final holistic reviewer (most capable model) over the whole M6b diff. Focus:
- **Deny-wins write gating:** only roles with `caps.knowledge_write` get `ORCH_KB_WRITE_TARGET` → only their MCP server offers the `write` tool. Confirm a read-only role's server has no write tool (`test_write_grant_*`, `test_read_grant_builds_search_only_server`) and the server refuses `write` with no target (`test_call_write_refused_when_not_granted`).
- **No worktree/diff pollution:** MCP config files are written outside the worktree (temp / `OPENCODE_CONFIG`); injected core files are excluded from the captured agent diff (`test_agent_step_gets_mcp_and_injects_core`).
- **Persistence root correctness:** the write target is rooted at the real repo (`Path(repo)`), not the discarded worktree — so the closed loop actually closes (`test_knowledge_closed_loop`).
- **Back-compat:** `_drive_harness`'s new `mcp_servers` default `()` and `_capture_diff`'s new `exclude` default `()` leave every M1–M6a call site unchanged; full suite stays green (≥190 prior + new).
- **Adapter parity:** both adapters translate `mcp_servers`; neither leaks the config into the worktree; no stderr deadlock (unchanged from M6a).
- **Scope:** no orchestrator-agent / `orch status` / safety-polish work.

Then use **superpowers:finishing-a-development-branch** to complete (merge to `orchestrator-design`, per the established milestone workflow).

## Self-Review (against spec §8 + the M6 decisions)

- **Spec §8 coverage:** core injection = files written into the session working dir (Task 4, wired Task 8) ✓ · on-demand lexical search exposed as `mcp__knowledge__search` (Tasks 1–3 server, Tasks 5–7 wiring) ✓ · gated `mcp__knowledge__write` granted only to write-holders, refused otherwise via deny-wins at the provider (Task 5) + server (Task 2) ✓ · MVP write = append to `.orchestrator/knowledge/lessons.md` (Task 2/5) ✓ · closed loop audit-writes→next-run-reads (Task 9) ✓ · no embeddings (Task 1 is lexical) ✓.
- **Placeholder scan:** every code step carries real code; the two looseness points (real-harness MCP wire format; the fake harness not opening MCP) are covered by explicit IMPLEMENTER NOTES + the follow-ups note, with the fakes pinning the contract (same pattern as M2/M6a). ✓
- **Type consistency:** `SearchResult`, `ServerState`, `handle_request`, `state_from_env`, `inject_core`, `build_knowledge_mcp` signatures match across tasks; `McpServer(name/command/args/env)` used identically in provider (Task 5) and both adapters (Tasks 6–7); `ORCH_KB_SOURCES`/`ORCH_KB_ROOT`/`ORCH_KB_WRITE_TARGET` env keys consistent between provider (writes them) and server (`state_from_env` reads them). ✓
- **Ordering risk:** Task 4 deliberately ships `inject_core` with a minimal import block; Task 5 extends imports for `build_knowledge_mcp` — flagged inline to avoid an F401 ruff failure between the two commits. ✓
- **Back-compat:** new params default to empty (`mcp_servers=()`, `exclude=()`); `run_task_step` and all prior `_drive_harness`/`_capture_diff` callers are untouched. ✓
