from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ToolRecord


MCP_PROTOCOL_VERSION = "2025-06-18"


def _parse_json_or_sse(body: bytes) -> Dict[str, Any]:
    text = body.decode("utf-8", "replace")
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    for line in stripped.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                return json.loads(payload)
    raise ValueError("response was neither JSON nor single-event SSE JSON")


def _post_json(url: str, payload: Dict[str, Any], session_id: str = "", timeout: int = 15) -> Tuple[Dict[str, Any], str]:
    headers = {
        "User-Agent": "mcp-newsletter/0.1",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        next_session = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id") or session_id
        return _parse_json_or_sse(body), next_session


def discover_remote_tools(provider: str, server_id: str, native_surface: str, url: str, timeout: int = 15) -> Tuple[List[ToolRecord], Dict[str, Any]]:
    if not url.startswith(("https://", "http://")):
        return [], {"ok": False, "error": "remote discovery requires http(s) url"}

    try:
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-newsletter", "version": "0.1.0"},
            },
        }
        _, session_id = _post_json(url, init_payload, timeout=timeout)
        tools_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        response, _ = _post_json(url, tools_payload, session_id=session_id, timeout=timeout)
    except HTTPError as exc:
        return [], {"ok": False, "status": exc.code, "error": str(exc)}
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return [], {"ok": False, "error": str(exc)}

    raw_tools = response.get("result", {}).get("tools", [])
    tools = []
    for raw in raw_tools:
        name = str(raw.get("name", "unknown"))
        tools.append(
            ToolRecord(
                provider=provider,
                server_id=server_id,
                name=name,
                native_surface=native_surface,
                description=str(raw.get("description", "")),
                input_schema=raw.get("inputSchema") or raw.get("input_schema") or {},
                annotations=raw.get("annotations") or {},
                source_urls=[url],
                raw=raw,
            )
        )
    return tools, {"ok": True, "tool_count": len(tools)}

