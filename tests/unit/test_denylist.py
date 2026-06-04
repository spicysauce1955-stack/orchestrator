from orchestrator.safety.denylist import GLOBAL_SHELL_DENY, merge_shell_deny


def test_global_deny_includes_destructive_commands():
    for pattern in ("rm -rf /", "git push --force", "git reset --hard", "DROP TABLE"):
        assert pattern in GLOBAL_SHELL_DENY


def test_merge_is_union_without_duplicates():
    merged = merge_shell_deny(["rm -rf /", "custom-cmd"])
    assert "custom-cmd" in merged
    assert merged.count("rm -rf /") == 1
    # global entries are preserved
    assert "git push --force" in merged
