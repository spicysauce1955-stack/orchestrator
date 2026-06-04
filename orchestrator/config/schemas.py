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
    def _infer_and_check_type(self) -> Step:
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
    def _unique_step_ids(self) -> Pipeline:
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
