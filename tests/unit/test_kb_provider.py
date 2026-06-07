from orchestrator.config.schemas import CoreKnowledge
from orchestrator.knowledge.provider import inject_core


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
