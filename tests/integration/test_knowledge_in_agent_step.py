import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import (
    Access,
    Config,
    CoreKnowledge,
    Harness,
    KnowledgeAccess,
    KnowledgeSource,
    Pipeline,
    Role,
    Step,
    StepType,
)
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    # uncommitted core file at repo root (so it is NOT already in a worktree off base)
    (repo / "AGENTS.md").write_text("project rules\n")
    return repo


def _ws():
    ws = Workspace(config=Config())
    ws.core_knowledge = CoreKnowledge(inject=["AGENTS.md"])
    ws.knowledge_sources = {"repo-conventions": KnowledgeSource(
        name="repo-conventions", sources=["docs/**"])}
    ws.roles = {"impl": Role(
        name="impl", harness=Harness.claude_code,
        access=Access(knowledge=KnowledgeAccess(read=["repo-conventions"])),
    )}
    return ws


async def test_agent_step_gets_mcp_and_injects_core(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    from orchestrator.runtime.executors import run_agent_step
    ws = _ws()
    repo = _repo(tmp_path)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", pipeline_name="p", inputs={"task": "x"})
    step = Step(id="implement", role="impl", type=StepType.agent, prompt="do {{task}}")
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter)
    # the harness was handed an MCP config (role has knowledge read)
    argv = (tmp_path / "argv.txt").read_text()
    assert "--mcp-config" in argv
    # the injected core file is NOT in the captured agent diff (core is never writable)
    assert "AGENTS.md" not in art.diff
