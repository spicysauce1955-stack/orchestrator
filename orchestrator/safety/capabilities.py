"""Capability resolution: role → ResolvedCaps (spec §4.1).

effective = (role grants ∪ skill grants) ∩ permission profile; deny always wins.
Translation to harness flags lives in the adapter (spec §5).
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import PermissionProfile, Role
from orchestrator.safety.denylist import merge_shell_deny

# Credential paths never readable by a harness (spec §4.1 dim 1 + 6).
CREDENTIAL_DENY_READ: tuple[str, ...] = (
    "~/.ssh",
    "~/.aws",
    "~/.kube",
    "~/.config/gh",
    ".env",
    ".env.*",
)
# Harness/VCS config is read-only (not writable) but still excluded from reads
# of secrets-bearing internals; we deny reads of these dirs by default.
CONFIG_DENY_READ: tuple[str, ...] = (".git", ".claude")

# Read-only tool floor and the edit tools a read-only profile must refuse.
_READ_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob")
_EDIT_TOOLS: tuple[str, ...] = ("Edit", "Write", "MultiEdit", "NotebookEdit")


@dataclass(frozen=True)
class ResolvedCaps:
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: str = "default"
    deny_read: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    network_egress: tuple[str, ...] = ()
    shell_deny: tuple[str, ...] = ()
    knowledge_read: tuple[str, ...] = ()
    knowledge_write: tuple[str, ...] = ()
    push_to_main: bool = False
    open_pr: bool = True

    @classmethod
    def read_only(cls) -> ResolvedCaps:
        """A minimal read-only capability set (used by tests + the planner)."""
        return cls(
            allowed_tools=_READ_TOOLS,
            disallowed_tools=_EDIT_TOOLS,
            permission_mode="default",
            deny_read=(*(_expand(p) for p in CREDENTIAL_DENY_READ), *CONFIG_DENY_READ),
            shell_deny=merge_shell_deny([]),
        )


def _expand(path: str) -> str:
    import os

    return os.path.expanduser(path) if path.startswith("~") else path


def _dedup(items: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for i in items:
        seen.setdefault(i, None)
    return tuple(seen)


def resolve_capabilities(role: Role, workspace: Workspace) -> ResolvedCaps:
    profile = role.permissions
    read_only = profile == PermissionProfile.read_only

    # --- Tools: read floor + skill grants, clamped by profile ---
    allowed: list[str] = list(_READ_TOOLS)
    for skill_name in role.skills:
        skill = workspace.skills.get(skill_name)
        if skill is None:
            continue
        for tool in skill.tools:
            allowed.append(tool)

    disallowed: list[str] = []
    if read_only:
        # deny-wins: edit tools removed from allow and added to deny
        allowed = [t for t in allowed if _base_tool(t) not in _EDIT_TOOLS]
        disallowed.extend(_EDIT_TOOLS)

    # --- Filesystem write scope (only meaningful for edit/full) ---
    write_scope: list[str] = []
    network: list[str] = []
    role_shell_deny: list[str] = []
    knowledge_read: list[str] = []
    knowledge_write: list[str] = []
    push_to_main = False
    open_pr = True

    access = role.access
    if access is not None:
        if access.filesystem is not None and not read_only:
            write_scope.extend(access.filesystem.write)
        if access.network is not None:
            network.extend(access.network.egress)
        if access.shell is not None:
            role_shell_deny.extend(access.shell.deny)
        if access.git is not None:
            push_to_main = bool(access.git.push_to_main)
            open_pr = bool(access.git.open_pr)
        if access.knowledge is not None:
            knowledge_read.extend(access.knowledge.read)
            # Knowledge write is NEVER in a preset — only explicit per-source.
            knowledge_write.extend(access.knowledge.write)

    # role.knowledge (top-level read grants) folds into knowledge_read
    knowledge_read.extend(role.knowledge)

    permission_mode = "default" if read_only else "acceptEdits"

    deny_read = (*tuple(_expand(p) for p in CREDENTIAL_DENY_READ), *CONFIG_DENY_READ)

    return ResolvedCaps(
        allowed_tools=_dedup(allowed),
        disallowed_tools=_dedup(disallowed),
        permission_mode=permission_mode,
        deny_read=deny_read,
        write_scope=_dedup(write_scope),
        network_egress=_dedup(network),
        shell_deny=merge_shell_deny(role_shell_deny),
        knowledge_read=_dedup(knowledge_read),
        knowledge_write=_dedup(knowledge_write),
        push_to_main=push_to_main,
        open_pr=open_pr,
    )


def _base_tool(tool: str) -> str:
    """`Bash(pytest)` → `Bash`; `Edit` → `Edit`."""
    return tool.split("(", 1)[0]
