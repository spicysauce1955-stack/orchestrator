import textwrap

import pytest

from orchestrator.config.loader import ConfigError, load_workspace


def _write(base, rel, content):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content))


def test_access_knowledge_write_must_reference_known_source(tmp_path):
    base = tmp_path / ".orchestrator"
    _write(base, "config.yaml", "defaults: {}\n")
    _write(base, "knowledge/repo-conventions.yaml", "sources: [docs/**]\nbackend: lexical\n")
    _write(
        base,
        "roles/auditor.yaml",
        """
        harness: claude-code
        permissions: read-only
        access:
          knowledge: { read: [repo-conventions], write: [ghost-source] }
        knowledge: [repo-conventions]
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "ghost-source" in str(exc.value)


def test_access_knowledge_read_must_reference_known_source(tmp_path):
    base = tmp_path / ".orchestrator"
    _write(base, "config.yaml", "defaults: {}\n")
    _write(base, "knowledge/repo-conventions.yaml", "sources: [docs/**]\n")
    _write(
        base,
        "roles/r.yaml",
        """
        harness: claude-code
        permissions: read-only
        access:
          knowledge: { read: [nope], write: [] }
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "nope" in str(exc.value)


def test_example_workspace_loads_clean():
    # The example declares a `lessons` source, so the auditor's write resolves.
    ws = load_workspace("examples/feature-pipeline/.orchestrator")
    assert "lessons" in ws.knowledge_sources
