# M1 — Config + Schemas + Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation milestone M1 of the orchestrator: a composable `.orchestrator/` config model (Pydantic), a loader that resolves references by name, and a compiler that lowers a pipeline to a validated graph + LangGraph `StateGraph` — surfaced through `orch compile`, which validates a pipeline with **no execution**.

**Architecture:** Three layers. (1) `config/` defines the typed authoring surface (roles, skills, knowledge, pipelines, steps, config) as Pydantic v2 models and a loader that reads `.orchestrator/` into a `Workspace` registry, resolving cross-references by name. (2) `compile/` builds a deterministic graph IR from a pipeline (`needs` → edges, `on_reject` → one conditional back-edge), runs validation (topo/cycle, typed-I/O references, `file_scope` overlap warnings), and lowers the IR to a LangGraph `StateGraph` with placeholder nodes (de-risks open question #13 — LangGraph impedance — without any execution or API cost). (3) `cli.py` exposes `orch compile`; `run`/`status`/`resume` are stubs for later milestones. A golden-graph test locks the compiled node/edge set so determinism can't silently drift.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, LangGraph 1.x (`langgraph.graph.StateGraph`), Typer (CLI), pytest, ruff. TDD throughout (spec §9): every behavior gets a failing test first.

---

## Spec references

- Design spec: `docs/superpowers/specs/2026-06-02-orchestrator-design.md`
- M1 definition (spec §12): "config + schemas + compiler: `orch compile` validates a pipeline (no execution)."
- Config model: spec §4 (roles/skills/knowledge/pipelines/config) and §4.1 (7-dimension access).
- Compiler behavior: spec §6 ("Compile" paragraph) — step→node, `needs`→edge, `on_reject`→conditional cyclic edge; compile-time validation: topo-sort (reject undeclared cycles), typed-I/O references, `file_scope` overlap warnings.
- Testing: spec §9 — unit (schema validation, compiler topo/typed-I/O/file_scope), golden-graph test (locks determinism).
- Repo layout: spec §11.

## M1 design decisions (locked here; flagged for later milestones)

These resolve ambiguities in the spec so the engineer has no open choices. Each is faithful to the spec and revisited in the named milestone.

1. **Step type inference.** A step's `type` is `agent` when `role` is set and `type` is omitted; `task` and `gate` must be set explicitly (they have no `role`). Matches every step in the spec's `feature.yaml`.
2. **Knowledge sources are named files under `knowledge/`.** `knowledge/core.yaml` → `CoreKnowledge` (always-injected files). Every other `knowledge/<name>.yaml` → a named `KnowledgeSource` (on-demand). Role/skill `knowledge: [name]` references resolve against `{core} ∪ {file stems}`. This preserves the spec's core-vs-index split (§8) while supporting the named sources roles reference (`repo-conventions`, `lessons`). The actual provider is built in **M6**; M1 only validates references.
3. **Access model is parsed and validated structurally but NOT resolved/translated in M1.** Capability *resolution* (deny-wins) and *translation* to harness flags is **M2+** (spec §4.1). M1 only ensures the `access:` block is well-formed.
4. **Reference grammar for typed-I/O.** Inside `prompt` strings, `<name>` references a pipeline input; `<stepid.output>` or `<stepid.output.field>` references a step's output (and optional output-schema field). M1 validates existence and field presence. Full artifact threading is **M3**.
5. **The compiled `StateGraph` uses placeholder node functions in M1** (no executors). Executors arrive in **M3**. M1 proves the IR lowers onto LangGraph cleanly (open question #13).

## File structure

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Package metadata, deps, `orch` entry point, pytest/ruff config |
| `orchestrator/__init__.py` | Package marker + version |
| `orchestrator/config/__init__.py` | Re-export public config symbols |
| `orchestrator/config/schemas.py` | All Pydantic v2 models + enums for the authoring surface |
| `orchestrator/config/loader.py` | Read `.orchestrator/` → `Workspace`; resolve references; `ConfigError` |
| `orchestrator/compile/__init__.py` | Re-export `compile_pipeline`, `CompileResult` |
| `orchestrator/compile/ir.py` | `Edge`, `GraphIR` dataclasses + `build_ir` |
| `orchestrator/compile/validate.py` | `validate_dag`, `validate_typed_io`, `validate_file_scope` |
| `orchestrator/compile/compiler.py` | `to_state_graph`, `compile_pipeline`, `CompileResult` |
| `orchestrator/cli.py` | Typer app: `compile` (+ `run`/`status`/`resume` stubs) |
| `examples/feature-pipeline/.orchestrator/...` | Canonical runnable example (the spec's pipeline) |
| `tests/unit/test_schemas.py` | Schema validation tests |
| `tests/unit/test_loader.py` | Loader + reference-resolution tests |
| `tests/unit/test_ir.py` | Graph IR construction tests |
| `tests/unit/test_validate.py` | DAG / typed-I/O / file_scope validation tests |
| `tests/unit/test_compiler.py` | `compile_pipeline` + golden-graph + LangGraph lowering tests |
| `tests/unit/test_cli.py` | CLI behavior + exit codes |
| `tests/integration/test_example_compiles.py` | End-to-end: example workspace compiles & matches golden graph |

---

## Task 1: Project scaffold & tooling

**Files:**
- Create: `pyproject.toml`
- Create: `orchestrator/__init__.py`
- Create: `orchestrator/config/__init__.py`
- Create: `orchestrator/compile/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`
- Test: `tests/unit/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_smoke.py`:
```python
def test_package_imports_and_has_version():
    import orchestrator

    assert isinstance(orchestrator.__version__, str)
    assert orchestrator.__version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator'`

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[project]
name = "orchestrator"
version = "0.1.0"
description = "Declarative multi-vendor coding-agent orchestrator"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "langgraph>=1.0",
    "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4"]

[project.scripts]
orch = "orchestrator.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["orchestrator"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 4: Create package markers**

`orchestrator/__init__.py`:
```python
"""Declarative multi-vendor coding-agent orchestrator."""

__version__ = "0.1.0"
```

`orchestrator/config/__init__.py`:
```python
```

`orchestrator/compile/__init__.py`:
```python
```

`tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` (all empty):
```python
```

- [ ] **Step 5: Install in editable mode**

Run: `python -m pip install -e ".[dev]"`
Expected: `Successfully installed orchestrator-0.1.0` (plus deps).

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_smoke.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml orchestrator tests
git commit -m "chore: scaffold orchestrator package (M1 task 1)"
```

---

## Task 2: Enums, budget, and access sub-models

**Files:**
- Create: `orchestrator/config/schemas.py`
- Test: `tests/unit/test_schemas.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_schemas.py`:
```python
import pytest
from pydantic import ValidationError

from orchestrator.config.schemas import (
    Access,
    Budget,
    GitAccess,
    Harness,
    Isolation,
    PermissionProfile,
    StepType,
)


def test_enum_values_match_spec():
    assert Harness.claude_code.value == "claude-code"
    assert Harness.opencode.value == "opencode"
    assert PermissionProfile.read_only.value == "read-only"
    assert Isolation.worktree.value == "worktree"
    assert StepType.agent.value == "agent"


def test_budget_defaults():
    b = Budget()
    assert b.max_usd == 5.0
    assert b.timeout_s == 1800


def test_git_access_defaults_are_safe():
    g = GitAccess()
    assert g.push_to_main is False
    assert g.open_pr is True


def test_access_block_parses_nested_dimensions():
    a = Access.model_validate(
        {
            "filesystem": {"write": ["src/**"], "read_only": [".git"]},
            "shell": {"deny": ["rm -rf"]},
            "git": {"push_to_main": False},
        }
    )
    assert a.filesystem.write == ["src/**"]
    assert a.shell.deny == ["rm -rf"]
    assert a.network is None


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Budget.model_validate({"max_usd": 1, "bogus": True})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.config.schemas'`

- [ ] **Step 3: Write the schemas (part 1)**

`orchestrator/config/schemas.py`:
```python
"""Pydantic models for the .orchestrator/ authoring surface (spec §4, §4.1)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Harness(str, Enum):
    claude_code = "claude-code"
    codex = "codex"
    opencode = "opencode"


class PermissionProfile(str, Enum):
    read_only = "read-only"
    edit = "edit"
    full = "full"


class Isolation(str, Enum):
    worktree = "worktree"
    container = "container"
    sandbox = "sandbox"


class StepType(str, Enum):
    task = "task"
    agent = "agent"
    gate = "gate"


class _Strict(BaseModel):
    """Base model that forbids unknown keys so config typos fail loudly."""

    model_config = ConfigDict(extra="forbid")


class Budget(_Strict):
    max_usd: float = 5.0
    timeout_s: int = 1800


class FilesystemAccess(_Strict):
    write: list[str] = Field(default_factory=list)
    read_only: list[str] = Field(default_factory=list)


class NetworkAccess(_Strict):
    egress: list[str] = Field(default_factory=list)


class ShellAccess(_Strict):
    deny: list[str] = Field(default_factory=list)


class GitAccess(_Strict):
    push_to_main: bool = False
    open_pr: bool = True


class KnowledgeAccess(_Strict):
    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)


class Access(_Strict):
    filesystem: FilesystemAccess | None = None
    network: NetworkAccess | None = None
    shell: ShellAccess | None = None
    git: GitAccess | None = None
    knowledge: KnowledgeAccess | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/config/schemas.py tests/unit/test_schemas.py
git commit -m "feat: config enums, budget, and access sub-models (M1 task 2)"
```

---

## Task 3: Role, Skill, and Knowledge schemas

**Files:**
- Modify: `orchestrator/config/schemas.py` (append)
- Test: `tests/unit/test_schemas.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/unit/test_schemas.py`)**

```python
def test_role_minimal_requires_harness():
    from orchestrator.config.schemas import PermissionProfile, Role

    r = Role.model_validate({"harness": "claude-code"})
    assert r.harness.value == "claude-code"
    assert r.permissions == PermissionProfile.edit  # default preset
    assert r.model is None
    assert r.skills == []
    assert r.budget.max_usd == 5.0


def test_role_full_parses_access_and_refs():
    from orchestrator.config.schemas import Role

    r = Role.model_validate(
        {
            "harness": "claude-code",
            "model": "opus",
            "permissions": "edit",
            "access": {"filesystem": {"write": ["src/**", "tests/**"]}},
            "skills": ["test-runner"],
            "knowledge": ["repo-conventions"],
            "mcp": ["repo-index"],
            "budget": {"max_usd": 5, "timeout_s": 1800},
        }
    )
    assert r.model == "opus"
    assert r.skills == ["test-runner"]
    assert r.access.filesystem.write == ["src/**", "tests/**"]


def test_role_rejects_unknown_harness():
    from pydantic import ValidationError

    from orchestrator.config.schemas import Role

    with pytest.raises(ValidationError):
        Role.model_validate({"harness": "cursor"})


def test_skill_requires_instructions():
    from orchestrator.config.schemas import Skill

    s = Skill.model_validate(
        {"instructions": "Run pytest -q after each change.", "tools": ["Bash(pytest)", "Read"]}
    )
    assert s.tools == ["Bash(pytest)", "Read"]


def test_core_and_index_knowledge():
    from orchestrator.config.schemas import CoreKnowledge, KnowledgeSource

    core = CoreKnowledge.model_validate({"inject": ["AGENTS.md", "docs/architecture.md"]})
    assert core.inject[0] == "AGENTS.md"

    idx = KnowledgeSource.model_validate({"sources": ["docs/**", "src/**"], "backend": "lexical"})
    assert idx.backend == "lexical"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'Role'`

- [ ] **Step 3: Append the schemas (part 2) to `orchestrator/config/schemas.py`**

```python
class Role(_Strict):
    name: str = ""  # populated from filename by the loader
    harness: Harness
    model: str | None = None
    permissions: PermissionProfile = PermissionProfile.edit
    access: Access | None = None
    skills: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    mcp: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)


class Skill(_Strict):
    name: str = ""  # populated from filename by the loader
    instructions: str
    tools: list[str] = Field(default_factory=list)
    mcp: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class CoreKnowledge(_Strict):
    """knowledge/core.yaml — files always injected into a session's working dir."""

    inject: list[str] = Field(default_factory=list)


class KnowledgeSource(_Strict):
    """Any knowledge/<name>.yaml other than core — on-demand lexical source."""

    name: str = ""  # populated from filename by the loader
    sources: list[str] = Field(default_factory=list)
    backend: str = "lexical"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/config/schemas.py tests/unit/test_schemas.py
git commit -m "feat: role, skill, knowledge schemas (M1 task 3)"
```

---

## Task 4: Step, Pipeline, and Config schemas (with type inference)

**Files:**
- Modify: `orchestrator/config/schemas.py` (append)
- Test: `tests/unit/test_schemas.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/unit/test_schemas.py`)**

```python
def test_step_with_role_infers_agent_type():
    from orchestrator.config.schemas import Step, StepType

    s = Step.model_validate({"id": "implement", "role": "implementer", "needs": ["plan"]})
    assert s.type == StepType.agent


def test_explicit_task_step_has_no_role():
    from orchestrator.config.schemas import Step, StepType

    s = Step.model_validate(
        {"id": "classify", "type": "task", "prompt": "Classify <task>"}
    )
    assert s.type == StepType.task
    assert s.role is None


def test_gate_step_rejects_role():
    from pydantic import ValidationError

    from orchestrator.config.schemas import Step

    with pytest.raises(ValidationError):
        Step.model_validate({"id": "approve", "type": "gate", "role": "auditor"})


def test_step_without_role_or_type_is_rejected():
    from pydantic import ValidationError

    from orchestrator.config.schemas import Step

    with pytest.raises(ValidationError):
        Step.model_validate({"id": "mystery"})


def test_pipeline_rejects_duplicate_step_ids():
    from pydantic import ValidationError

    from orchestrator.config.schemas import Pipeline

    with pytest.raises(ValidationError):
        Pipeline.model_validate(
            {
                "steps": [
                    {"id": "a", "type": "task", "prompt": "x"},
                    {"id": "a", "type": "task", "prompt": "y"},
                ]
            }
        )


def test_config_defaults():
    from orchestrator.config.schemas import Config, Isolation

    c = Config()
    assert c.defaults.isolation == Isolation.worktree
    assert c.defaults.mode == "declarative"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'Step'`

- [ ] **Step 3: Append the schemas (part 3) to `orchestrator/config/schemas.py`**

```python
class Step(_Strict):
    id: str
    type: StepType | None = None  # inferred from `role` when omitted
    role: str | None = None
    prompt: str | None = None
    output_schema: dict | None = None
    needs: list[str] = Field(default_factory=list)
    file_scope: list[str] = Field(default_factory=list)
    isolation: Isolation | None = None
    success_criteria: str | None = None
    max_retries: int = 0
    on_reject: str | None = None
    require_approval: bool = False
    merge_strategy: str | None = None

    @model_validator(mode="after")
    def _infer_and_check_type(self) -> "Step":
        if self.type is None:
            if self.role is not None:
                self.type = StepType.agent
            else:
                raise ValueError(
                    f"step '{self.id}': cannot infer type — set `type` or `role`"
                )
        if self.type == StepType.agent and self.role is None:
            raise ValueError(f"step '{self.id}': agent step requires `role`")
        if self.type in (StepType.task, StepType.gate) and self.role is not None:
            raise ValueError(
                f"step '{self.id}': {self.type.value} step must not set `role`"
            )
        return self


class Pipeline(_Strict):
    name: str = ""  # populated from filename by the loader
    mode: str = "declarative"  # declarative | agentic
    inputs: dict[str, str] = Field(default_factory=dict)
    steps: list[Step]

    @model_validator(mode="after")
    def _unique_step_ids(self) -> "Pipeline":
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id '{step.id}'")
            seen.add(step.id)
        return self


class Defaults(_Strict):
    isolation: Isolation = Isolation.worktree
    mode: str = "declarative"
    budget: Budget = Field(default_factory=Budget)
    observability_sink: str = "sqlite"


class Config(_Strict):
    defaults: Defaults = Field(default_factory=Defaults)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_schemas.py -v`
Expected: PASS (all schema tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/config/schemas.py tests/unit/test_schemas.py
git commit -m "feat: step/pipeline/config schemas with type inference (M1 task 4)"
```

---

## Task 5: Config loader & reference resolution

**Files:**
- Create: `orchestrator/config/loader.py`
- Modify: `orchestrator/config/__init__.py`
- Test: `tests/unit/test_loader.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_loader.py`:
```python
from pathlib import Path

import pytest

from orchestrator.config.loader import ConfigError, load_workspace


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _minimal_workspace(root: Path) -> Path:
    base = root / ".orchestrator"
    _write(base, "config.yaml", "defaults:\n  isolation: worktree\n")
    _write(base, "roles/implementer.yaml", "harness: claude-code\nskills: [test-runner]\n")
    _write(base, "skills/test-runner.yaml", "instructions: Run pytest -q\ntools: [Read]\n")
    _write(base, "knowledge/core.yaml", "inject: [AGENTS.md]\n")
    _write(
        base,
        "pipelines/feature.yaml",
        "steps:\n"
        "  - id: implement\n"
        "    role: implementer\n",
    )
    return base


def test_load_workspace_populates_registries(tmp_path):
    base = _minimal_workspace(tmp_path)
    ws = load_workspace(base)

    assert ws.roles["implementer"].harness.value == "claude-code"
    assert ws.roles["implementer"].name == "implementer"
    assert ws.skills["test-runner"].instructions.startswith("Run pytest")
    assert ws.core_knowledge.inject == ["AGENTS.md"]
    assert "feature" in ws.pipelines
    assert ws.pipelines["feature"].steps[0].id == "implement"


def test_named_knowledge_source_loads(tmp_path):
    base = _minimal_workspace(tmp_path)
    _write(base, "knowledge/repo-conventions.yaml", "sources: [docs/**]\nbackend: lexical\n")
    ws = load_workspace(base)
    assert ws.knowledge_sources["repo-conventions"].sources == ["docs/**"]


def test_dangling_skill_reference_raises(tmp_path):
    base = _minimal_workspace(tmp_path)
    _write(base, "roles/implementer.yaml", "harness: claude-code\nskills: [missing-skill]\n")
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "missing-skill" in str(exc.value)


def test_pipeline_step_role_reference_validated(tmp_path):
    base = _minimal_workspace(tmp_path)
    _write(
        base,
        "pipelines/feature.yaml",
        "steps:\n  - id: implement\n    role: ghost\n",
    )
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "ghost" in str(exc.value)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_workspace(tmp_path / "nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.config.loader'`

- [ ] **Step 3: Write the loader**

`orchestrator/config/loader.py`:
```python
"""Load and cross-validate a .orchestrator/ workspace (spec §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from orchestrator.config.schemas import (
    Config,
    CoreKnowledge,
    KnowledgeSource,
    Pipeline,
    Role,
    Skill,
)


class ConfigError(Exception):
    """Raised when a workspace is malformed or has dangling references."""


@dataclass
class Workspace:
    config: Config
    roles: dict[str, Role] = field(default_factory=dict)
    skills: dict[str, Skill] = field(default_factory=dict)
    core_knowledge: CoreKnowledge | None = None
    knowledge_sources: dict[str, KnowledgeSource] = field(default_factory=dict)
    pipelines: dict[str, Pipeline] = field(default_factory=dict)

    def knowledge_names(self) -> set[str]:
        names = set(self.knowledge_sources)
        if self.core_knowledge is not None:
            names.add("core")
        return names


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - exercised via malformed yaml
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at top level")
    return data


def _load_dir(base: Path, subdir: str, model, into: dict) -> None:
    directory = base / subdir
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.yaml")):
        name = path.stem
        try:
            obj = model.model_validate({**_read_yaml(path), "name": name})
        except Exception as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        into[name] = obj


def load_workspace(base: Path) -> Workspace:
    base = Path(base)
    if not base.is_dir():
        raise ConfigError(f"{base}: workspace directory not found")

    config_path = base / "config.yaml"
    config = Config.model_validate(_read_yaml(config_path)) if config_path.is_file() else Config()
    ws = Workspace(config=config)

    _load_dir(base, "roles", Role, ws.roles)
    _load_dir(base, "skills", Skill, ws.skills)
    _load_dir(base, "pipelines", Pipeline, ws.pipelines)

    knowledge_dir = base / "knowledge"
    if knowledge_dir.is_dir():
        for path in sorted(knowledge_dir.glob("*.yaml")):
            if path.stem == "core":
                ws.core_knowledge = CoreKnowledge.model_validate(_read_yaml(path))
            else:
                ws.knowledge_sources[path.stem] = KnowledgeSource.model_validate(
                    {**_read_yaml(path), "name": path.stem}
                )

    _resolve_references(ws)
    return ws


def _resolve_references(ws: Workspace) -> None:
    errors: list[str] = []
    known_knowledge = ws.knowledge_names()

    for role in ws.roles.values():
        for skill in role.skills:
            if skill not in ws.skills:
                errors.append(f"role '{role.name}' references unknown skill '{skill}'")
        for source in role.knowledge:
            if source not in known_knowledge:
                errors.append(f"role '{role.name}' references unknown knowledge '{source}'")

    for skill in ws.skills.values():
        for source in skill.knowledge:
            if source not in known_knowledge:
                errors.append(f"skill '{skill.name}' references unknown knowledge '{source}'")

    for pipeline in ws.pipelines.values():
        for step in pipeline.steps:
            if step.role is not None and step.role not in ws.roles:
                errors.append(
                    f"pipeline '{pipeline.name}' step '{step.id}' references unknown role "
                    f"'{step.role}'"
                )

    if errors:
        raise ConfigError("; ".join(errors))
```

- [ ] **Step 4: Export public symbols**

`orchestrator/config/__init__.py`:
```python
from orchestrator.config.loader import ConfigError, Workspace, load_workspace

__all__ = ["ConfigError", "Workspace", "load_workspace"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_loader.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/config/loader.py orchestrator/config/__init__.py tests/unit/test_loader.py
git commit -m "feat: workspace loader with reference resolution (M1 task 5)"
```

---

## Task 6: Graph IR construction

**Files:**
- Create: `orchestrator/compile/ir.py`
- Test: `tests/unit/test_ir.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ir.py`:
```python
from orchestrator.compile.ir import Edge, build_ir
from orchestrator.config.schemas import Pipeline


def _pipeline() -> Pipeline:
    return Pipeline.model_validate(
        {
            "steps": [
                {"id": "classify", "type": "task", "prompt": "Classify <task>"},
                {"id": "plan", "role": "planner", "needs": ["classify"]},
                {"id": "implement", "role": "implementer", "needs": ["plan"], "max_retries": 2},
                {"id": "review", "role": "reviewer", "needs": ["implement"], "on_reject": "implement"},
                {"id": "test", "role": "implementer", "needs": ["review"]},
            ]
        }
    )


def test_nodes_match_step_ids():
    ir = build_ir(_pipeline())
    assert ir.nodes == ["classify", "plan", "implement", "review", "test"]


def test_needs_become_edges():
    ir = build_ir(_pipeline())
    assert Edge("classify", "plan") in ir.edges
    assert Edge("plan", "implement") in ir.edges
    assert Edge("implement", "review") in ir.edges


def test_on_reject_is_a_conditional_back_edge():
    ir = build_ir(_pipeline())
    assert Edge("review", "implement", conditional=True) in ir.edges
    # review's forward edge becomes conditional too (router chooses reject vs forward)
    assert Edge("review", "test", conditional=True) in ir.edges


def test_entrypoints_and_terminals():
    ir = build_ir(_pipeline())
    assert ir.entrypoints == ["classify"]
    assert ir.terminals == ["test"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_ir.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.compile.ir'`

- [ ] **Step 3: Write the IR**

`orchestrator/compile/ir.py`:
```python
"""Deterministic graph IR derived from a pipeline (spec §6 "Compile")."""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.config.schemas import Pipeline


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    conditional: bool = False


@dataclass
class GraphIR:
    nodes: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    terminals: list[str] = field(default_factory=list)


def build_ir(pipeline: Pipeline) -> GraphIR:
    steps = pipeline.steps
    by_id = {s.id: s for s in steps}

    # A step that declares on_reject is a branch point: ALL of its outgoing edges
    # (forward successors + the reject back-edge) are conditional.
    reject_sources = {s.id for s in steps if s.on_reject}

    raw: list[Edge] = []
    for s in steps:
        for dep in s.needs:
            raw.append(Edge(dep, s.id))
    for s in steps:
        if s.on_reject:
            raw.append(Edge(s.id, s.on_reject))

    edges = [
        Edge(e.source, e.target, conditional=e.source in reject_sources) for e in raw
    ]

    needed = {dep for s in steps for dep in s.needs}
    entrypoints = [s.id for s in steps if not s.needs]
    terminals = [
        s.id for s in steps if s.id not in needed and not by_id[s.id].on_reject
    ]

    return GraphIR(
        nodes=[s.id for s in steps],
        edges=edges,
        entrypoints=entrypoints,
        terminals=terminals,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_ir.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/compile/ir.py tests/unit/test_ir.py
git commit -m "feat: graph IR construction (needs + on_reject edges) (M1 task 6)"
```

---

## Task 7: DAG validation (topo / cycle / dangling needs)

**Files:**
- Create: `orchestrator/compile/validate.py`
- Test: `tests/unit/test_validate.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_validate.py`:
```python
from orchestrator.compile.validate import validate_dag
from orchestrator.config.schemas import Pipeline


def _p(steps: list[dict]) -> Pipeline:
    return Pipeline.model_validate({"steps": steps})


def test_valid_linear_pipeline_has_no_errors():
    p = _p(
        [
            {"id": "a", "type": "task", "prompt": "x"},
            {"id": "b", "type": "task", "prompt": "y", "needs": ["a"]},
        ]
    )
    assert validate_dag(p) == []


def test_dangling_needs_reported():
    p = _p([{"id": "b", "type": "task", "prompt": "y", "needs": ["a"]}])
    errors = validate_dag(p)
    assert any("unknown step 'a'" in e for e in errors)


def test_undeclared_cycle_in_needs_reported():
    p = _p(
        [
            {"id": "a", "type": "task", "prompt": "x", "needs": ["b"]},
            {"id": "b", "type": "task", "prompt": "y", "needs": ["a"]},
        ]
    )
    errors = validate_dag(p)
    assert any("cycle" in e.lower() for e in errors)


def test_on_reject_back_edge_is_allowed():
    p = _p(
        [
            {"id": "impl", "role": "implementer"},
            {"id": "review", "role": "reviewer", "needs": ["impl"], "on_reject": "impl"},
        ]
    )
    assert validate_dag(p) == []


def test_on_reject_to_unknown_step_reported():
    p = _p(
        [
            {"id": "impl", "role": "implementer"},
            {"id": "review", "role": "reviewer", "needs": ["impl"], "on_reject": "ghost"},
        ]
    )
    errors = validate_dag(p)
    assert any("ghost" in e for e in errors)


def test_on_reject_must_point_upstream():
    p = _p(
        [
            {"id": "a", "role": "x", "on_reject": "b"},
            {"id": "b", "role": "y", "needs": ["a"]},
        ]
    )
    errors = validate_dag(p)
    assert any("upstream" in e.lower() for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.compile.validate'`

- [ ] **Step 3: Write DAG validation**

`orchestrator/compile/validate.py`:
```python
"""Compile-time pipeline validation (spec §6).

Errors block compilation; warnings do not. Three independent checks:
  - validate_dag: dangling needs, undeclared cycles, on_reject targeting.
  - validate_typed_io: prompt reference resolution (Task 8).
  - validate_file_scope: overlapping write scopes on concurrent steps (Task 9).
"""

from __future__ import annotations

from orchestrator.config.schemas import Pipeline


def _ancestors(step_id: str, deps: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(deps.get(step_id, []))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in deps:
            continue
        seen.add(cur)
        stack.extend(deps[cur])
    return seen


def _has_cycle(ids: list[str], deps: dict[str, list[str]]) -> bool:
    # Kahn's algorithm over the needs-only graph (on_reject edges excluded).
    indegree = {i: 0 for i in ids}
    for node in ids:
        for dep in deps[node]:
            if dep in indegree:
                indegree[node] += 1
    queue = [i for i in ids if indegree[i] == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for node in ids:
            if cur in deps[node]:
                indegree[node] -= 1
                if indegree[node] == 0:
                    queue.append(node)
    return visited != len(ids)


def validate_dag(pipeline: Pipeline) -> list[str]:
    errors: list[str] = []
    ids = [s.id for s in pipeline.steps]
    id_set = set(ids)
    deps = {s.id: list(s.needs) for s in pipeline.steps}

    for step in pipeline.steps:
        for dep in step.needs:
            if dep not in id_set:
                errors.append(f"step '{step.id}' needs unknown step '{dep}'")
            if dep == step.id:
                errors.append(f"step '{step.id}' cannot depend on itself")

    # Cycles in the forward (needs-only) graph are undeclared cycles.
    if all(d in id_set for s in pipeline.steps for d in s.needs):
        if _has_cycle(ids, deps):
            errors.append("pipeline has an undeclared cycle in `needs` edges")

    for step in pipeline.steps:
        if step.on_reject is None:
            continue
        if step.on_reject not in id_set:
            errors.append(
                f"step '{step.id}' on_reject targets unknown step '{step.on_reject}'"
            )
        elif step.on_reject not in _ancestors(step.id, deps):
            errors.append(
                f"step '{step.id}' on_reject must point to an upstream step, got "
                f"'{step.on_reject}'"
            )

    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_validate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/compile/validate.py tests/unit/test_validate.py
git commit -m "feat: DAG validation (cycles, dangling needs, on_reject) (M1 task 7)"
```

---

## Task 8: Typed-I/O reference validation

**Files:**
- Modify: `orchestrator/compile/validate.py` (append `validate_typed_io`)
- Test: `tests/unit/test_validate.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/unit/test_validate.py`)**

```python
from orchestrator.compile.validate import validate_typed_io


def test_input_reference_resolves():
    p = Pipeline.model_validate(
        {
            "inputs": {"task": "string"},
            "steps": [{"id": "classify", "type": "task", "prompt": "Classify <task>"}],
        }
    )
    assert validate_typed_io(p) == []


def test_unknown_input_reference_reported():
    p = Pipeline.model_validate(
        {
            "inputs": {"task": "string"},
            "steps": [{"id": "classify", "type": "task", "prompt": "Use <goal>"}],
        }
    )
    errors = validate_typed_io(p)
    assert any("goal" in e for e in errors)


def test_step_output_reference_resolves():
    p = Pipeline.model_validate(
        {
            "steps": [
                {
                    "id": "classify",
                    "type": "task",
                    "prompt": "x",
                    "output_schema": {"kind": "enum[bugfix,feature]"},
                },
                {
                    "id": "plan",
                    "type": "task",
                    "prompt": "Plan for <classify.output.kind>",
                    "needs": ["classify"],
                },
            ]
        }
    )
    assert validate_typed_io(p) == []


def test_unknown_step_output_field_reported():
    p = Pipeline.model_validate(
        {
            "steps": [
                {
                    "id": "classify",
                    "type": "task",
                    "prompt": "x",
                    "output_schema": {"kind": "enum[bugfix]"},
                },
                {
                    "id": "plan",
                    "type": "task",
                    "prompt": "Plan <classify.output.missing>",
                    "needs": ["classify"],
                },
            ]
        }
    )
    errors = validate_typed_io(p)
    assert any("missing" in e for e in errors)


def test_reference_to_unknown_step_reported():
    p = Pipeline.model_validate(
        {"steps": [{"id": "a", "type": "task", "prompt": "Use <ghost.output>"}]}
    )
    errors = validate_typed_io(p)
    assert any("ghost" in e for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_validate.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_typed_io'`

- [ ] **Step 3: Append `validate_typed_io` to `orchestrator/compile/validate.py`**

Add this import near the top of the file (replace the existing `from __future__` block's following import line region by adding `re`):
```python
import re
```

Append at the end of the file:
```python
_REF = re.compile(r"<([a-zA-Z_][\w.-]*)>")


def validate_typed_io(pipeline: Pipeline) -> list[str]:
    errors: list[str] = []
    by_id = {s.id: s for s in pipeline.steps}
    inputs = set(pipeline.inputs)

    for step in pipeline.steps:
        if not step.prompt:
            continue
        for token in _REF.findall(step.prompt):
            parts = token.split(".")
            head = parts[0]

            # Bare <name> -> pipeline input.
            if len(parts) == 1:
                if head not in inputs:
                    errors.append(
                        f"step '{step.id}': reference <{token}> matches no pipeline input"
                    )
                continue

            # <stepid.output[.field]> -> another step's output.
            if head not in by_id:
                errors.append(
                    f"step '{step.id}': reference <{token}> targets unknown step '{head}'"
                )
                continue
            if len(parts) >= 2 and parts[1] != "output":
                errors.append(
                    f"step '{step.id}': reference <{token}> must use '.output' "
                    f"(got '.{parts[1]}')"
                )
                continue
            if len(parts) == 3:
                schema = by_id[head].output_schema or {}
                if parts[2] not in schema:
                    errors.append(
                        f"step '{step.id}': reference <{token}> field '{parts[2]}' not in "
                        f"output_schema of '{head}'"
                    )

    return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_validate.py -v`
Expected: PASS (all DAG + typed-I/O tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/compile/validate.py tests/unit/test_validate.py
git commit -m "feat: typed-I/O reference validation (M1 task 8)"
```

---

## Task 9: file_scope overlap warnings

**Files:**
- Modify: `orchestrator/compile/validate.py` (append `validate_file_scope`)
- Test: `tests/unit/test_validate.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/unit/test_validate.py`)**

```python
from orchestrator.compile.validate import validate_file_scope


def test_no_overlap_no_warnings():
    p = Pipeline.model_validate(
        {
            "steps": [
                {"id": "a", "role": "x", "file_scope": ["src/**"]},
                {"id": "b", "role": "y", "needs": ["a"], "file_scope": ["tests/**"]},
            ]
        }
    )
    assert validate_file_scope(p) == []


def test_concurrent_steps_with_identical_scope_warn():
    # a and b are concurrent (neither depends on the other) and share a scope.
    p = Pipeline.model_validate(
        {
            "steps": [
                {"id": "root", "type": "task", "prompt": "x"},
                {"id": "a", "role": "x", "needs": ["root"], "file_scope": ["src/**"]},
                {"id": "b", "role": "y", "needs": ["root"], "file_scope": ["src/**"]},
            ]
        }
    )
    warnings = validate_file_scope(p)
    assert any("a" in w and "b" in w and "src/**" in w for w in warnings)


def test_sequential_steps_sharing_scope_do_not_warn():
    # b depends on a, so they never run concurrently.
    p = Pipeline.model_validate(
        {
            "steps": [
                {"id": "a", "role": "x", "file_scope": ["src/**"]},
                {"id": "b", "role": "y", "needs": ["a"], "file_scope": ["src/**"]},
            ]
        }
    )
    assert validate_file_scope(p) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_validate.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_file_scope'`

- [ ] **Step 3: Append `validate_file_scope` to `orchestrator/compile/validate.py`**

```python
def validate_file_scope(pipeline: Pipeline) -> list[str]:
    """Warn when two steps that may run concurrently declare overlapping write scope.

    Two steps are concurrent when neither is an ancestor (transitive `needs`) of the
    other. Scope overlap (M1) = an exact glob shared between the two scope lists.
    """
    warnings: list[str] = []
    deps = {s.id: list(s.needs) for s in pipeline.steps}
    scoped = [s for s in pipeline.steps if s.file_scope]

    for i, a in enumerate(scoped):
        a_anc = _ancestors(a.id, deps)
        for b in scoped[i + 1 :]:
            b_anc = _ancestors(b.id, deps)
            concurrent = a.id not in b_anc and b.id not in a_anc
            if not concurrent:
                continue
            shared = sorted(set(a.file_scope) & set(b.file_scope))
            for glob in shared:
                warnings.append(
                    f"steps '{a.id}' and '{b.id}' may run concurrently and both write "
                    f"'{glob}'"
                )
    return warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_validate.py -v`
Expected: PASS (all validation tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/compile/validate.py tests/unit/test_validate.py
git commit -m "feat: file_scope overlap warnings for concurrent steps (M1 task 9)"
```

---

## Task 10: Compiler — lower IR to LangGraph + CompileResult + golden graph

**Files:**
- Create: `orchestrator/compile/compiler.py`
- Modify: `orchestrator/compile/__init__.py`
- Test: `tests/unit/test_compiler.py`

This task de-risks open question #13 (LangGraph impedance): it proves the IR lowers onto a LangGraph `StateGraph` that compiles, with `on_reject` as a conditional edge — without executing anything.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_compiler.py`:
```python
from orchestrator.compile.compiler import CompileResult, compile_pipeline, to_state_graph
from orchestrator.compile.ir import build_ir
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Pipeline, Role


def _workspace() -> Workspace:
    pipeline = Pipeline.model_validate(
        {
            "name": "feature",
            "inputs": {"task": "string"},
            "steps": [
                {"id": "classify", "type": "task", "prompt": "Classify <task>"},
                {"id": "plan", "role": "planner", "needs": ["classify"]},
                {"id": "implement", "role": "implementer", "needs": ["plan"], "max_retries": 2},
                {
                    "id": "review",
                    "role": "reviewer",
                    "needs": ["implement"],
                    "on_reject": "implement",
                },
                {"id": "test", "role": "implementer", "needs": ["review"]},
            ],
        }
    )
    roles = {
        name: Role.model_validate({"harness": "claude-code"})
        for name in ("planner", "implementer", "reviewer")
    }
    for name, role in roles.items():
        role.name = name
    return Workspace(config=Config(), roles=roles, pipelines={"feature": pipeline})


def test_compile_ok_pipeline_has_no_errors():
    result = compile_pipeline(_workspace(), "feature")
    assert isinstance(result, CompileResult)
    assert result.ok
    assert result.errors == []


def test_compile_unknown_pipeline_errors():
    result = compile_pipeline(_workspace(), "ghost")
    assert not result.ok
    assert any("ghost" in e for e in result.errors)


def test_golden_graph_node_and_edge_set_is_stable():
    result = compile_pipeline(_workspace(), "feature")
    nodes = set(result.ir.nodes)
    edges = {(e.source, e.target, e.conditional) for e in result.ir.edges}

    assert nodes == {"classify", "plan", "implement", "review", "test"}
    assert edges == {
        ("classify", "plan", False),
        ("plan", "implement", False),
        ("implement", "review", False),
        ("review", "test", True),
        ("review", "implement", True),
    }


def test_lowers_to_compilable_langgraph_state_graph():
    pipeline = _workspace().pipelines["feature"]
    ir = build_ir(pipeline)
    compiled = to_state_graph(pipeline, ir)
    drawn = compiled.get_graph()
    # Every IR node must exist in the LangGraph (plus LangGraph's __start__/__end__).
    assert {"classify", "plan", "implement", "review", "test"} <= set(drawn.nodes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_compiler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.compile.compiler'`

- [ ] **Step 3: Write the compiler**

`orchestrator/compile/compiler.py`:
```python
"""Compile a pipeline to a validated IR + LangGraph StateGraph (spec §6).

M1 lowers to LangGraph with placeholder node functions (no execution). This proves
the typed-pipeline + on_reject cycle map cleanly onto StateGraph (open question #13).
Real step executors arrive in M3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from orchestrator.compile.ir import GraphIR, build_ir
from orchestrator.compile.validate import (
    validate_dag,
    validate_file_scope,
    validate_typed_io,
)
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline


@dataclass
class CompileResult:
    pipeline: str
    ir: GraphIR | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class RunState(TypedDict, total=False):
    """Placeholder run state for M1 lowering; expanded with artifacts/cost in M3."""

    status: str


def _placeholder_node(state: RunState) -> dict:
    # M1: nodes do nothing. Executors are wired in M3.
    return {}


def to_state_graph(pipeline: Pipeline, ir: GraphIR):
    builder = StateGraph(RunState)
    for node in ir.nodes:
        builder.add_node(node, _placeholder_node)

    for entry in ir.entrypoints:
        builder.add_edge(START, entry)
    for terminal in ir.terminals:
        builder.add_edge(terminal, END)

    # Group outgoing edges by source so conditional sources get a single router.
    outgoing: dict[str, list] = {}
    for edge in ir.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    for source, edges in outgoing.items():
        if any(e.conditional for e in edges):
            targets = [e.target for e in edges]

            def _router(state: RunState, _targets=targets) -> str:
                # M1 placeholder: forward path is deterministic. The verdict-driven
                # branch is implemented with the review loop in M4.
                return _targets[0]

            builder.add_conditional_edges(source, _router, targets)
        else:
            for edge in edges:
                builder.add_edge(edge.source, edge.target)

    return builder.compile()


def compile_pipeline(workspace: Workspace, pipeline_name: str) -> CompileResult:
    pipeline = workspace.pipelines.get(pipeline_name)
    if pipeline is None:
        available = ", ".join(sorted(workspace.pipelines)) or "(none)"
        return CompileResult(
            pipeline=pipeline_name,
            errors=[f"unknown pipeline '{pipeline_name}'; available: {available}"],
        )

    errors = validate_dag(pipeline)
    if not errors:
        errors = validate_typed_io(pipeline)
    warnings = validate_file_scope(pipeline)

    if errors:
        return CompileResult(pipeline=pipeline_name, errors=errors, warnings=warnings)

    ir = build_ir(pipeline)
    # Prove the graph lowers and compiles; surface any LangGraph friction as an error.
    try:
        to_state_graph(pipeline, ir)
    except Exception as exc:  # pragma: no cover - guards open question #13
        return CompileResult(
            pipeline=pipeline_name,
            ir=ir,
            errors=[f"LangGraph lowering failed: {exc}"],
            warnings=warnings,
        )

    return CompileResult(pipeline=pipeline_name, ir=ir, warnings=warnings)
```

- [ ] **Step 4: Export public symbols**

`orchestrator/compile/__init__.py`:
```python
from orchestrator.compile.compiler import CompileResult, compile_pipeline, to_state_graph
from orchestrator.compile.ir import Edge, GraphIR, build_ir

__all__ = [
    "CompileResult",
    "Edge",
    "GraphIR",
    "build_ir",
    "compile_pipeline",
    "to_state_graph",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_compiler.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/compile/compiler.py orchestrator/compile/__init__.py tests/unit/test_compiler.py
git commit -m "feat: compiler lowers IR to LangGraph + golden graph (M1 task 10)"
```

---

## Task 11: CLI — `orch compile` (+ run/status/resume stubs)

**Files:**
- Create: `orchestrator/cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_cli.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app

runner = CliRunner()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _good_workspace(root: Path) -> Path:
    base = root / ".orchestrator"
    _write(base, "config.yaml", "defaults:\n  isolation: worktree\n")
    _write(base, "roles/planner.yaml", "harness: claude-code\n")
    _write(
        base,
        "pipelines/feature.yaml",
        "inputs: {task: string}\n"
        "steps:\n"
        "  - id: classify\n"
        "    type: task\n"
        "    prompt: Classify <task>\n"
        "  - id: plan\n"
        "    role: planner\n"
        "    needs: [classify]\n",
    )
    return base


def test_compile_ok_exits_zero(tmp_path):
    base = _good_workspace(tmp_path)
    result = runner.invoke(app, ["compile", "feature", "--root", str(base)])
    assert result.exit_code == 0
    assert "OK" in result.stdout
    assert "classify" in result.stdout


def test_compile_with_errors_exits_one(tmp_path):
    base = _good_workspace(tmp_path)
    # Break it: plan needs a nonexistent step.
    _write(
        base,
        "pipelines/feature.yaml",
        "steps:\n  - id: plan\n    role: planner\n    needs: [ghost]\n",
    )
    result = runner.invoke(app, ["compile", "feature", "--root", str(base)])
    assert result.exit_code == 1
    assert "ghost" in result.stdout


def test_compile_unknown_pipeline_exits_one(tmp_path):
    base = _good_workspace(tmp_path)
    result = runner.invoke(app, ["compile", "nope", "--root", str(base)])
    assert result.exit_code == 1


def test_run_stub_is_not_implemented(tmp_path):
    result = runner.invoke(app, ["run", "feature"])
    assert result.exit_code != 0
    assert "not implemented" in result.stdout.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.cli'`

- [ ] **Step 3: Write the CLI**

`orchestrator/cli.py`:
```python
"""orch CLI. M1 implements `compile`; run/status/resume are later milestones."""

from __future__ import annotations

from pathlib import Path

import typer

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import ConfigError, load_workspace

app = typer.Typer(help="Declarative multi-vendor coding-agent orchestrator.")


@app.command()
def compile(
    pipeline: str = typer.Argument(..., help="Pipeline name (file stem under pipelines/)."),
    root: Path = typer.Option(
        Path(".orchestrator"), "--root", help="Path to the .orchestrator/ workspace."
    ),
) -> None:
    """Validate and compile a pipeline (no execution)."""
    try:
        workspace = load_workspace(root)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}")
        raise typer.Exit(1) from exc

    result = compile_pipeline(workspace, pipeline)

    for warning in result.warnings:
        typer.echo(f"warning: {warning}")

    if not result.ok:
        for error in result.errors:
            typer.echo(f"error: {error}")
        typer.echo(f"FAILED: pipeline '{pipeline}' did not compile.")
        raise typer.Exit(1)

    typer.echo(f"OK: pipeline '{pipeline}' compiled.")
    typer.echo(f"nodes: {', '.join(result.ir.nodes)}")
    for edge in result.ir.edges:
        arrow = "-?->" if edge.conditional else "-->"
        typer.echo(f"  {edge.source} {arrow} {edge.target}")


def _not_implemented(name: str) -> None:
    typer.echo(f"`orch {name}` is not implemented in M1 (config + compiler only).")
    raise typer.Exit(2)


@app.command()
def run(pipeline: str = typer.Argument(...)) -> None:
    """Execute a pipeline (later milestone)."""
    _not_implemented("run")


@app.command()
def status(run_id: str = typer.Argument(...)) -> None:
    """Show a run's status (later milestone)."""
    _not_implemented("status")


@app.command()
def resume(run_id: str = typer.Argument(...)) -> None:
    """Resume an interrupted run (later milestone)."""
    _not_implemented("resume")


if __name__ == "__main__":  # pragma: no cover
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_cli.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/cli.py tests/unit/test_cli.py
git commit -m "feat: orch compile CLI + run/status/resume stubs (M1 task 11)"
```

---

## Task 12: Canonical example workspace + end-to-end integration test

This ships the spec's `feature.yaml` (spec §4) as a real, runnable example and proves the whole stack compiles it.

**Files:**
- Create: `examples/feature-pipeline/.orchestrator/config.yaml`
- Create: `examples/feature-pipeline/.orchestrator/roles/{implementer,reviewer,planner,auditor}.yaml`
- Create: `examples/feature-pipeline/.orchestrator/skills/test-runner.yaml`
- Create: `examples/feature-pipeline/.orchestrator/knowledge/{core.yaml,repo-conventions.yaml}`
- Create: `examples/feature-pipeline/.orchestrator/pipelines/feature.yaml`
- Test: `tests/integration/test_example_compiles.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_example_compiles.py`:
```python
from pathlib import Path

from orchestrator.compile.compiler import compile_pipeline
from orchestrator.config.loader import load_workspace

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def test_example_workspace_loads():
    ws = load_workspace(EXAMPLE)
    assert set(ws.roles) == {"implementer", "reviewer", "planner", "auditor"}
    assert "test-runner" in ws.skills
    assert ws.core_knowledge.inject  # non-empty
    assert "feature" in ws.pipelines


def test_example_feature_pipeline_compiles():
    ws = load_workspace(EXAMPLE)
    result = compile_pipeline(ws, "feature")
    assert result.ok, result.errors
    assert set(result.ir.nodes) == {
        "classify",
        "plan",
        "implement",
        "review",
        "test",
        "audit",
        "approve",
        "merge",
    }


def test_example_review_loop_is_conditional():
    ws = load_workspace(EXAMPLE)
    result = compile_pipeline(ws, "feature")
    edges = {(e.source, e.target, e.conditional) for e in result.ir.edges}
    assert ("review", "implement", True) in edges
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_example_compiles.py -v`
Expected: FAIL — `ConfigError: .../examples/... workspace directory not found`

- [ ] **Step 3: Create the example config files**

`examples/feature-pipeline/.orchestrator/config.yaml`:
```yaml
defaults:
  isolation: worktree
  mode: declarative
  budget: { max_usd: 5, timeout_s: 1800 }
  observability_sink: sqlite
```

`examples/feature-pipeline/.orchestrator/roles/implementer.yaml`:
```yaml
harness: claude-code
model: opus
permissions: edit
access:
  filesystem: { write: ["src/**", "tests/**"], read_only: [".git", ".claude"] }
  network: { egress: ["pypi.org", "github.com"] }
  shell: { deny: ["rm -rf", "git push --force", "DROP TABLE"] }
  git: { push_to_main: false, open_pr: true }
  knowledge: { read: ["repo-conventions"], write: [] }
skills: [test-runner]
knowledge: [repo-conventions]
budget: { max_usd: 5, timeout_s: 1800 }
```

`examples/feature-pipeline/.orchestrator/roles/reviewer.yaml`:
```yaml
harness: claude-code
permissions: read-only
knowledge: [repo-conventions]
```

`examples/feature-pipeline/.orchestrator/roles/planner.yaml`:
```yaml
harness: claude-code
permissions: read-only
knowledge: [repo-conventions]
```

`examples/feature-pipeline/.orchestrator/roles/auditor.yaml`:
```yaml
harness: claude-code
permissions: read-only
access:
  knowledge: { read: ["repo-conventions"], write: ["lessons"] }
knowledge: [repo-conventions]
```

`examples/feature-pipeline/.orchestrator/skills/test-runner.yaml`:
```yaml
instructions: "Run `pytest -q` after each change; never delete or weaken tests."
tools: ["Bash(pytest)", "Read", "Edit"]
```

`examples/feature-pipeline/.orchestrator/knowledge/core.yaml`:
```yaml
inject: [AGENTS.md, docs/architecture.md]
```

`examples/feature-pipeline/.orchestrator/knowledge/repo-conventions.yaml`:
```yaml
sources: [docs/**, src/**]
backend: lexical
```

`examples/feature-pipeline/.orchestrator/pipelines/feature.yaml`:
```yaml
mode: declarative
inputs: { task: string }
steps:
  - id: classify
    type: task
    prompt: "Classify <task> as: bugfix | feature | refactor"
    output_schema: { kind: "enum[bugfix,feature,refactor]" }
  - id: plan
    role: planner
    needs: [classify]
  - id: implement
    role: implementer
    needs: [plan]
    file_scope: ["src/**"]
    isolation: worktree
    success_criteria: "pytest -q"
    max_retries: 2
  - id: review
    role: reviewer
    needs: [implement]
    on_reject: implement
  - id: test
    role: implementer
    needs: [review]
    success_criteria: "pytest -q && ruff check"
  - id: audit
    role: auditor
    needs: [test]
  - id: approve
    type: gate
    needs: [audit]
    require_approval: true
  - id: merge
    type: task
    needs: [approve]
    merge_strategy: sequential-rebase
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_example_compiles.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Verify the CLI works against the real example**

Run: `python -m orchestrator.cli compile feature --root examples/feature-pipeline/.orchestrator`
Expected output (order of warnings/edges may vary):
```
OK: pipeline 'feature' compiled.
nodes: classify, plan, implement, review, test, audit, approve, merge
  classify --> plan
  plan --> implement
  implement --> review
  review -?-> test
  review -?-> implement
  test --> audit
  audit --> approve
  approve --> merge
```

- [ ] **Step 6: Commit**

```bash
git add examples tests/integration/test_example_compiles.py
git commit -m "feat: canonical example workspace + end-to-end compile test (M1 task 12)"
```

---

## Task 13: Full suite green + lint + milestone verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS — all tests across `tests/unit/` and `tests/integration/`.

- [ ] **Step 2: Run the linter**

Run: `python -m ruff check .`
Expected: `All checks passed!` (fix any findings, re-run until clean.)

- [ ] **Step 3: Verify the M1 acceptance criterion end-to-end**

Run: `python -m orchestrator.cli compile feature --root examples/feature-pipeline/.orchestrator`
Expected: exit code 0 and the node/edge listing from Task 12 Step 5.

Run (negative check): introduce a temporary dangling `needs` in a copy and confirm exit code 1 — or simply confirm via the CLI tests already covering this. Do **not** leave the workspace modified.

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint clean + M1 verification" || echo "nothing to commit"
```

---

## Self-review (run against the spec)

**1. Spec coverage (M1 scope, spec §12 + §10 "Built & runnable" subset relevant to M1):**

| Spec requirement | Task |
|------------------|------|
| Composable `.orchestrator/` config + Pydantic schemas (§4) | Tasks 2–4, 5 |
| 7-dimension access model parsed/validated structurally (§4.1) | Task 2 (`Access` + sub-models); resolution deferred to M2 (decision #3) |
| Loader resolves role/skill/knowledge references by name (§3 "Config loader") | Task 5 |
| Compiler: step→node, needs→edge, on_reject→conditional cyclic edge (§6) | Tasks 6, 10 |
| Compile-time validation: topo-sort / reject undeclared cycles (§6) | Task 7 |
| Typed-I/O reference checks (§6) | Task 8 |
| `file_scope` overlap warnings (§6) | Task 9 |
| Lowers to LangGraph `StateGraph`; de-risk #13 (§6, §13) | Task 10 |
| Golden-graph test locks determinism (§9) | Tasks 10, 12 |
| CLI `orch compile` validates a pipeline, no execution (§12 M1) | Task 11 |
| `run`/`status`/`resume` present as stubs (§3 CLI surface) | Task 11 |
| Schema-validation + compiler unit tests (§9) | Tasks 2–4, 6–10 |

Out of M1 scope (correctly deferred, named in decisions): capability resolution/translation (M2), executors & artifact threading (M3), review-loop routing logic (M4), HITL/merge (M5), knowledge provider/observability/OpenCode adapter (M6).

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". Every code step contains complete code; every test step contains complete tests. ✅

**3. Type consistency:** `Workspace`, `Role`, `Skill`, `CoreKnowledge`, `KnowledgeSource`, `Pipeline`, `Step`, `Config`, `Edge`, `GraphIR`, `CompileResult`, `RunState` are defined once and referenced consistently. `build_ir`/`to_state_graph`/`compile_pipeline`/`validate_dag`/`validate_typed_io`/`validate_file_scope`/`load_workspace`/`ConfigError` signatures match between definition and all call sites and tests. `_ancestors` is defined in Task 7 and reused in Task 9 (same module). ✅

---

## Execution handoff

Chosen for this milestone (confirmed with the user): **subagent-driven execution in an isolated git worktree.**

- REQUIRED SUB-SKILL at execution time: `superpowers:using-git-worktrees` (create the isolated workspace) then `superpowers:subagent-driven-development` (fresh subagent per task + two-stage review between tasks).
- Each task is independently committable; review checkpoints sit between tasks.
- Tasks 2→3→4 and 7→8→9 touch the same files in sequence and must run in order; Tasks 5 and 6 are independent of each other; Tasks 10–12 depend on everything before them.
```