# M8 — recipe/template library + `orch init` (2026-06-10)

Branch `m8-template-library`, plan `docs/superpowers/plans/2026-06-10-m8-template-library.md`,
TDD, **347 tests green** (was 334), ruff clean. Implements spec §4.2 — the
adoption lever: vetted recipes + one-command scaffolding. No engine changes.

## What landed

- `orchestrator/templates/` — in-package data trees, each `<name>/template.yaml`
  (one-line `description`) + a complete `.orchestrator/`:
  - **review-heavy** — full governance (classify→plan→implement→review⟲→test→
    audit→approve HITL→merge); promoted from `examples/feature-pipeline`
    (`full.yaml`), incl. knowledge sources (core/repo-conventions/lessons/
    candidates) and the auditor vetting grant from M7.
  - **bugfix-fast** — implement→test→merge, single edit role, no review/HITL.
  - **mixed-harness** — task classify → implement on OpenCode (zhipu/glm-4.6) →
    review on Claude (`{{implement.diff}}`, on_reject loop) → merge.
- `orchestrator/templates/__init__.py` — `Template`, `list_templates()`,
  `scaffold(name, dest, force=False)` (whole-tree copy; refuses an existing
  `.orchestrator/` without force; force replaces wholesale — recipes are never
  merged).
- CLI: `orch init [--template review-heavy] [--dest] [--force] [--list]` and
  `orch new --template <name>` (alias with required template).
- **Integrity invariant locked by test:** every shipped template scaffolds and
  every pipeline in it compiles (`test_every_template_scaffolds_and_compiles`).

## Deferred / follow-ups

- Templates as wheel package-data: works from a source checkout (data files
  live inside the package); verify inclusion when a real wheel build/publish
  lands (no build pipeline exists yet).
- No per-template variable interpolation (e.g. project name) — YAGNI for now.
- No scaffolding from arbitrary paths/URLs; curated set only.
- `examples/feature-pipeline` retained as the test fixture workspace; templates
  are curated copies, not symlinks — keep them in sync deliberately.
