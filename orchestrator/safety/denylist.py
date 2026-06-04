"""Global shell command deny-list (spec §4.1 dim 3). Deny always wins."""

from __future__ import annotations

# Hard-blocked command fragments, merged with any per-role shell deny.
GLOBAL_SHELL_DENY: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf",
    "git push --force",
    "git reset --hard",
    "curl|bash",
    "curl | bash",
    "DROP TABLE",
    "npm publish",
)


def merge_shell_deny(role_deny: list[str]) -> tuple[str, ...]:
    """Union the global deny-list with a role's deny-list, order-stable, no dups."""
    seen: dict[str, None] = {}
    for item in (*GLOBAL_SHELL_DENY, *role_deny):
        seen.setdefault(item, None)
    return tuple(seen)
