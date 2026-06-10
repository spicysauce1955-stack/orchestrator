# M8 — Recipe/Template Library + `orch init` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A curated, in-package library of vetted pipeline templates plus `orch init` / `orch new --template <name>` that seed a working `.orchestrator/` in one command (spec §4.2 — adoption lever, not a new engine capability).

**Architecture:** Templates are plain data trees under `orchestrator/templates/<name>/` (each: a `template.yaml` manifest with a `description`, and a complete `.orchestrator/` tree promoted/curated from `examples/`). A small API in `orchestrator/templates/__init__.py` (`list_templates()`, `scaffold(name, dest, force=False)`) locates them via `Path(__file__).parent`. The CLI wraps it. The integrity invariant — *every shipped template scaffolds and compiles* — is locked by a parametrized test (scaffold → `load_workspace` → `compile_pipeline` for every pipeline in the template).

**Tech Stack:** Python 3.11, shutil.copytree, Typer, pytest. No new deps.

**Templates (3):**
- `review-heavy` — full governance: classify→plan→implement→review⟲→test→audit→approve(HITL)→merge; roles planner/implementer/reviewer/auditor; knowledge core+repo-conventions+lessons+candidates (mirrors `examples/feature-pipeline` `full.yaml`).
- `bugfix-fast` — minimal: implement→test→merge; one `implementer` role; no HITL.
- `mixed-harness` — classify(task)→implement on OpenCode→review on Claude→merge; proves harness≠model.

---

### Task 1: template data trees

**Files:** Create `orchestrator/templates/<name>/template.yaml` + `orchestrator/templates/<name>/.orchestrator/**` for the three templates above (adapt from `examples/feature-pipeline/.orchestrator`: real schema — `harness: claude-code|opencode`, `permissions: read-only|edit`, `output_schema: {verdict: "enum[approve,reject]"}`, gate step `type: gate, require_approval: true`, merge step `type: task, merge_strategy: sequential-rebase`).

- [ ] Write the trees. No test yet (Task 3's integrity test covers them); commit as data.

### Task 2: `list_templates()`

**Files:** Create `orchestrator/templates/__init__.py`; Test: `tests/unit/test_templates.py`

- [ ] Failing test: `list_templates()` returns the 3 templates sorted by name, each with non-empty `description` (from `template.yaml`) and an existing `path` containing `.orchestrator/`.
- [ ] Implement `Template` dataclass + scan of `Path(__file__).parent` for dirs holding `template.yaml` + `.orchestrator/`.
- [ ] PASS → commit.

### Task 3: `scaffold()` + the compile-integrity invariant

**Files:** modify `orchestrator/templates/__init__.py`; extend `tests/unit/test_templates.py`

- [ ] Failing tests: `scaffold("review-heavy", dest)` copies `.orchestrator/` (returns created rel paths); existing `dest/.orchestrator` → `TemplateError` unless `force=True`; unknown name → `TemplateError` listing valid names.
- [ ] Failing test (parametrized over `list_templates()`): scaffold each template into tmp, `load_workspace(dest/".orchestrator")`, `compile_pipeline` every `ws.pipelines` entry → `result.ok`.
- [ ] Implement scaffold (copytree); fix any template that doesn't compile.
- [ ] PASS → commit.

### Task 4: CLI `orch init` + `orch new`

**Files:** modify `orchestrator/cli.py`; extend `tests/unit/test_templates.py` (CliRunner)

- [ ] Failing tests: `orch init --dest <tmp>` scaffolds the default (`review-heavy`) and prints created files; `orch init --list` prints names+descriptions, exits 0, creates nothing; `orch init --template nope` → exit 1 with valid names; existing workspace → exit 1 advising `--force`; `orch new --template bugfix-fast --dest <tmp>` scaffolds.
- [ ] Implement both commands (thin wrappers over the API).
- [ ] PASS; full suite + ruff → commit.

### Task 5: note + merge

- [ ] `docs/superpowers/notes/2026-06-10-m8-templates.md`; full suite + ruff; merge `m8-template-library` → main (no-ff), push.

## Self-review
- §4.2 coverage: curated named recipes (3) ✓ versioned-with-the-package ✓ `orch init` ✓ `orch new --template` ✓ seeds a *working* workspace (compile-integrity test) ✓.
- YAGNI: no remote template registry, no per-template variables/interpolation, no `--template` from arbitrary paths (can land later if asked).
