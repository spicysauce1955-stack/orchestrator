import json
import sys

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, CoreKnowledge, KnowledgeSource
from orchestrator.knowledge.provider import build_knowledge_mcp, inject_core
from orchestrator.safety.capabilities import ResolvedCaps


def test_injects_files_into_dest(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("be careful\n")
    (root / "docs").mkdir()
    (root / "docs" / "arch.md").write_text("layers\n")
    dest = tmp_path / "wt"
    dest.mkdir()

    injected = inject_core(CoreKnowledge(inject=["AGENTS.md", "docs/arch.md"]), root, dest)

    assert injected == ["AGENTS.md", "docs/arch.md"]
    assert (dest / "AGENTS.md").read_text() == "be careful\n"
    assert (dest / "docs" / "arch.md").read_text() == "layers\n"


def test_missing_source_is_skipped(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("x\n")
    dest = tmp_path / "wt"
    dest.mkdir()
    injected = inject_core(CoreKnowledge(inject=["AGENTS.md", "nope.md"]), root, dest)
    assert injected == ["AGENTS.md"]
    assert not (dest / "nope.md").exists()


def test_none_core_injects_nothing(tmp_path):
    dest = tmp_path / "wt"
    dest.mkdir()
    assert inject_core(None, tmp_path, dest) == []


# --- MCP descriptor tests ---


def _ws():
    ws = Workspace(config=Config())
    ws.knowledge_sources = {
        "repo-conventions": KnowledgeSource(
            name="repo-conventions", sources=["docs/**"]
        ),
        "lessons": KnowledgeSource(
            name="lessons", sources=[".orchestrator/knowledge/lessons.md"]
        ),
    }
    return ws


def test_no_grants_yields_no_server(tmp_path):
    caps = ResolvedCaps()  # no knowledge_read / knowledge_write
    assert build_knowledge_mcp(_ws(), caps, tmp_path) == []


def test_read_grant_builds_search_only_server(tmp_path):
    caps = ResolvedCaps(knowledge_read=("repo-conventions",))
    [srv] = build_knowledge_mcp(_ws(), caps, tmp_path)
    assert srv.name == "knowledge"
    assert srv.command == sys.executable
    assert srv.args == ["-m", "orchestrator.knowledge.mcp_server"]
    assert json.loads(srv.env["ORCH_KB_SOURCES"]) == ["docs/**"]
    assert srv.env["ORCH_KB_ROOT"] == str(tmp_path)
    assert "ORCH_KB_WRITE_TARGET" not in srv.env  # read-only -> no write tool


def test_write_grant_sets_write_target(tmp_path):
    caps = ResolvedCaps(knowledge_read=("lessons",), knowledge_write=("lessons",))
    [srv] = build_knowledge_mcp(_ws(), caps, tmp_path)
    assert srv.env["ORCH_KB_WRITE_TARGET"] == str(
        tmp_path / ".orchestrator/knowledge/lessons.md"
    )


def test_multiple_read_sources_merge_globs(tmp_path):
    caps = ResolvedCaps(knowledge_read=("repo-conventions", "lessons"))
    [srv] = build_knowledge_mcp(_ws(), caps, tmp_path)
    assert json.loads(srv.env["ORCH_KB_SOURCES"]) == [
        "docs/**",
        ".orchestrator/knowledge/lessons.md",
    ]
