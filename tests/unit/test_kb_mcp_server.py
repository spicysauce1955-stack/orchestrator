from orchestrator.knowledge.mcp_server import ServerState, handle_request


def _state(tmp_path, write=False):
    (tmp_path / "kb.md").write_text("lesson: always rebase before merge\n")
    target = tmp_path / "lessons.md" if write else None
    return ServerState(sources=["*.md"], root=tmp_path, write_target=target)


def test_initialize_advertises_tools(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _state(tmp_path)
    )
    assert resp["id"] == 1
    assert resp["result"]["capabilities"]["tools"] == {}
    assert resp["result"]["serverInfo"]["name"] == "knowledge"


def test_initialized_notification_returns_none(tmp_path):
    assert handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, _state(tmp_path)
    ) is None


def test_tools_list_search_only_without_write(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, _state(tmp_path, write=False)
    )
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"search"}


def test_tools_list_includes_write_when_granted(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, _state(tmp_path, write=True)
    )
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"search", "write"}


def test_call_search_returns_text_content(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "search", "arguments": {"query": "rebase"}}},
        _state(tmp_path),
    )
    block = resp["result"]["content"][0]
    assert block["type"] == "text"
    assert "rebase" in block["text"].lower()
    assert resp["result"]["isError"] is False


def test_call_write_appends_to_target(tmp_path):
    st = _state(tmp_path, write=True)
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "write", "arguments": {"lesson": "prefer 3way apply"}}},
        st,
    )
    assert resp["result"]["isError"] is False
    assert "prefer 3way apply" in st.write_target.read_text()


def test_call_write_refused_when_not_granted(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "write", "arguments": {"lesson": "x"}}},
        _state(tmp_path, write=False),
    )
    assert resp["result"]["isError"] is True


def test_unknown_method_returns_error(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "bogus/method"}, _state(tmp_path)
    )
    assert resp["error"]["code"] == -32601


def test_ping_returns_empty_result(tmp_path):
    resp = handle_request({"jsonrpc": "2.0", "id": 7, "method": "ping"}, _state(tmp_path))
    assert resp["result"] == {}


def test_call_write_empty_lesson_is_error(tmp_path):
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "write", "arguments": {"lesson": "   "}}},
        _state(tmp_path, write=True),
    )
    assert resp["result"]["isError"] is True
