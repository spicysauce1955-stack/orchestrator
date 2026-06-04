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
