"""TDD spec for SENTINEL's MCP endpoint: the agent's tools exposed as MCP,
with the SAME policy path as everything else — in live mode every tools/call
routes through the Pomerium proxy; in local mode the in-process gate decides.
A denied tool call must surface as an MCP tool error, never a silent success.

    .venv/bin/python -m pytest tests/test_mcp.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from sentinel.app import app  # noqa: E402

client = TestClient(app)


def rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method,
                                  "params": params or {}})
    assert r.status_code == 200
    return r.json()


def test_initialize_advertises_tools_capability():
    out = rpc("initialize")
    assert out["result"]["serverInfo"]["name"] == "sentinel"
    assert "tools" in out["result"]["capabilities"]


def test_tools_list_exposes_registry_with_schemas():
    out = rpc("tools/list")
    tools = {t["name"]: t for t in out["result"]["tools"]}
    assert "rotate_logs" in tools and "restart_service" in tools
    assert len(tools) == 7
    props = tools["rotate_logs"]["inputSchema"]["properties"]
    assert "service" in props


def test_tools_call_allowed_tool_executes():
    out = rpc("tools/call", {"name": "rotate_logs",
                             "arguments": {"service": "checkout-api"}})
    res = out["result"]
    assert res.get("isError") is not True
    text = res["content"][0]["text"]
    assert "rotated" in text and "policy" in text  # detail + policy verdict cited


def test_tools_call_prod_db_restart_is_denied_as_tool_error():
    out = rpc("tools/call", {"name": "restart_service",
                             "arguments": {"service": "billing-db"}})
    res = out["result"]
    assert res["isError"] is True
    text = res["content"][0]["text"].lower()
    assert "blocked" in text or "denied" in text


def test_unknown_tool_is_jsonrpc_error():
    out = rpc("tools/call", {"name": "drop_database",
                             "arguments": {"service": "billing-db"}})
    assert "error" in out and out["error"]["code"] == -32602


def test_unknown_service_is_tool_error_not_crash():
    out = rpc("tools/call", {"name": "rotate_logs",
                             "arguments": {"service": "no-such-svc"}})
    res = out["result"]
    assert res["isError"] is True


def test_unknown_method_is_jsonrpc_error():
    out = rpc("no/such/method")
    assert out["error"]["code"] == -32601
