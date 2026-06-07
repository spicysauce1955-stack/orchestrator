from orchestrator.knowledge.lexical import SearchResult, search


def _make_repo(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text(
        "Worktrees isolate each agent.\nNever push to main directly.\n"
    )
    (tmp_path / "docs" / "b.md").write_text("Unrelated content about widgets.\n")
    (tmp_path / "notes.txt").write_text("worktree cleanup happens on success.\n")
    return tmp_path


def test_finds_matching_lines_case_insensitive(tmp_path):
    root = _make_repo(tmp_path)
    results = search("WORKTREE", ["docs/**", "*.txt"], root, limit=10)
    paths = {r.path for r in results}
    assert "docs/a.md" in paths
    assert "notes.txt" in paths
    assert "docs/b.md" not in paths


def test_result_carries_path_line_and_snippet(tmp_path):
    root = _make_repo(tmp_path)
    [hit] = [r for r in search("push to main", ["docs/**"], root, limit=10)
             if r.path == "docs/a.md"]
    assert isinstance(hit, SearchResult)
    assert hit.line == 2
    assert "push to main" in hit.snippet.lower()


def test_ranking_prefers_more_term_hits(tmp_path):
    root = tmp_path
    (root / "many.md").write_text("agent agent agent worktree\n")
    (root / "few.md").write_text("agent once\n")
    results = search("agent worktree", ["*.md"], root, limit=10)
    assert results[0].path == "many.md"


def test_limit_caps_results(tmp_path):
    root = tmp_path
    for i in range(5):
        (root / f"f{i}.md").write_text("match here\n")
    assert len(search("match", ["*.md"], root, limit=3)) == 3


def test_no_match_returns_empty(tmp_path):
    (tmp_path / "x.md").write_text("nothing relevant\n")
    assert search("zzz", ["*.md"], tmp_path, limit=10) == []
