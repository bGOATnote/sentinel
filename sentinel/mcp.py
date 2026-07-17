"""SENTINEL's tools as an MCP server (JSON-RPC 2.0 over HTTP at POST /mcp).

The point: an external agent (Claude, an IDE, another loop) gets SENTINEL's hands —
and EVERY tools/call goes through the same policy path as the agent itself: in
Pomerium-live mode the call is proxied and PPL decides (a denied tool is a 403 from
the proxy, surfaced here as an MCP tool error). The model — any model — can ask;
the policy layer disposes. This mirrors Pomerium's own MCP guardrail pattern
(mcp_tool criteria) in a self-hosted, offline-capable form.
"""
from __future__ import annotations

from typing import Any

from .registry import TOOL_DESCRIPTIONS, Registry

PROTOCOL_VERSION = "2025-06-18"


def _tool_defs(world) -> list[dict]:
    services = sorted(world.services)
    return [{
        "name": name,
        "description": f"{desc} (policy-gated: prod-db class actions are denied)",
        "inputSchema": {
            "type": "object",
            "properties": {"service": {"type": "string", "enum": services}},
            "required": ["service"],
        },
    } for name, desc in TOOL_DESCRIPTIONS.items()]


def _err(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _res(id_: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def handle(payload: dict, registry: Registry) -> dict:
    id_ = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params") or {}

    if method == "initialize":
        return _res(id_, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "sentinel", "version": "0.1.0"},
            "capabilities": {"tools": {}},
        })
    if method in ("notifications/initialized", "ping"):
        return _res(id_, {})
    if method == "tools/list":
        return _res(id_, {"tools": _tool_defs(registry.world)})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        if name not in TOOL_DESCRIPTIONS:
            return _err(id_, -32602, f"unknown tool '{name}'")
        service = str(args.get("service", ""))
        if service not in registry.world.services:
            return _res(id_, {"isError": True, "content": [{
                "type": "text",
                "text": f"error: unknown service '{service}'"}]})
        r = registry.call(name, service)
        if r.blocked:
            return _res(id_, {"isError": True, "content": [{
                "type": "text",
                "text": f"BLOCKED by {r.policy_via}: {r.rule}"}]})
        return _res(id_, {"isError": False, "content": [{
            "type": "text",
            "text": f"{r.detail} · policy: {r.rule} (via {r.policy_via})"}]})
    return _err(id_, -32601, f"method '{method}' not found")
