# M1 Review Follow-ups

> From the final holistic code review of M1 (2026-06-04). M1 shipped **ready-with-minor-nits**:
> 51 tests green, ruff clean, LangGraph lowering verified (open question #13 closed — no impedance).
> None of the items below are correctness bugs for valid M1 inputs; they are deferred deliberately.

## By design (already-documented M1 simplifications — fold into the named milestone)

- **Typed-I/O dataflow ordering (M3).** `validate_typed_io` resolves `<step.output>` as long as the
  step *exists*, even without a `needs` edge or if defined later. Plan decision #4 scopes full
  artifact threading to M3. When M3 adds artifact threading, also require the referenced step to be
  in the referencing step's transitive ancestors (`_ancestors`).
- **`access.knowledge.read/write` not cross-validated (M2).** Loader only validates the top-level
  `role.knowledge` list. `access.knowledge.write: [lessons]` in the example references an undefined
  source and loads clean. Plan decision #3 scopes capability resolution to M2.

## Design decision needed (needs user/spec input — do NOT fix unilaterally)

- **Reference syntax vs. prose angle brackets (`validate.py` `_REF`).** The regex `<([a-zA-Z_]…)>`
  treats any `<word>` in a prompt as a reference, so a legitimate prompt like ``create a `List<T>` ``
  fails to compile ("`<T>` matches no pipeline input"). The spec itself chose bare `<task>` /
  `<step.output>` syntax, so this is a spec-level tension, not just an impl bug. Resolve by choosing a
  less collision-prone convention (e.g. `${…}` or `{{…}}`) or a documented escaping rule.

## Cheap hardening (safe pure-wins; pick up opportunistically)

- **Cycle masked by dangling guard (`validate.py` `validate_dag`).** The `if all(d in id_set …)`
  guard suppresses cycle reporting when a dangling `needs` is also present. `_has_cycle` is already
  robust to dangling deps (deps is keyed by all step ids), so the guard can be dropped to report both
  errors. Add a test: `a needs [b, ghost]`, `b needs [a]` → expect both errors.
- **Deep field refs unvalidated.** `<a.output.k.deep>` (4+ segments) passes unchecked. Reject
  `len(parts) > 3` (nested-schema validation is out of M1 scope).
- **`mode` as enum.** `Pipeline.mode` / `Defaults.mode` are free `str`; a typo like `declaritive`
  passes silently and `mode` gates the M5/M6 Controller seam. Promote to an enum
  (`declarative | agentic`) early in M2.
- **Golden test under-locks order.** `test_compiler.py` asserts the edge *set*; edge order is in fact
  deterministic and the CLI prints in order, so consider asserting the ordered list to lock it.
- **Untested branch.** The LangGraph-lowering-failure path in `compiler.py` (`pragma: no cover`) and
  the dangling-guard branch are untested. Self-need emits a redundant double error (cosmetic).
