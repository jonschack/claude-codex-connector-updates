from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from ..context import CollectContext
from ..mcp_discovery import discover_remote_tools
from ..models import ServerRecord, ToolRecord
from ..utils import read_json, redact_secrets


PROVIDER = "codex"


def _plugin_root() -> Path:
    default = str(Path.home() / ".codex" / "plugins")
    return Path(os.environ.get("MCP_NEWSLETTER_CODEX_PLUGIN_ROOT", default)).expanduser()


def _read_local_json(ctx: CollectContext, label: str, path: Path) -> Dict[str, Any]:
    data = read_json(path, default={})
    if data:
        ctx.save_raw_json(PROVIDER, label, redact_secrets(data))
    return data or {}


def collect_codex(ctx: CollectContext) -> List[ServerRecord]:
    root = _plugin_root()
    marketplace_path = root / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_path.exists():
        ctx.add_issue(PROVIDER, str(marketplace_path), "Codex plugin marketplace not found")
        return []

    marketplace = _read_local_json(ctx, "marketplace", marketplace_path)
    servers: List[ServerRecord] = []
    for entry in marketplace.get("plugins", []):
        plugin_name = entry.get("name", "unknown")
        source_path = entry.get("source", {}).get("path", f"./plugins/{plugin_name}")
        plugin_dir = (root / source_path).resolve()
        manifest_path = plugin_dir / ".codex-plugin" / "plugin.json"
        app_path = plugin_dir / ".app.json"
        mcp_path = plugin_dir / ".mcp.json"

        manifest = _read_local_json(ctx, f"{plugin_name}-plugin-manifest", manifest_path) if manifest_path.exists() else {}
        app_manifest = _read_local_json(ctx, f"{plugin_name}-app", app_path) if app_path.exists() else {}
        mcp_manifest = _read_local_json(ctx, f"{plugin_name}-mcp", mcp_path) if mcp_path.exists() else {}

        interface = manifest.get("interface", {})
        capabilities = list(interface.get("capabilities") or [])
        description = manifest.get("description") or interface.get("longDescription") or interface.get("shortDescription") or ""
        mcp_servers = mcp_manifest.get("mcpServers", {})
        transport = "app" if app_manifest else "plugin"
        if mcp_servers:
            transport = "mcp"

        tools: List[ToolRecord] = []
        discovery: Dict[str, Any] = {}
        for mcp_name, config in mcp_servers.items():
            clean_config = redact_secrets(config)
            url = clean_config.get("url", "")
            if url and clean_config.get("type", "http") in {"http", "sse", "streamable-http"} and not ctx.skip_network:
                discovered, result = discover_remote_tools(PROVIDER, plugin_name, "plugin", url)
                discovery[mcp_name] = result
                for tool in discovered:
                    tool.name = f"{mcp_name}.{tool.name}"
                    tools.append(tool)
            else:
                discovery[mcp_name] = {
                    "ok": False,
                    "reason": "local_or_unconfigured_mcp_discovery_deferred",
                    "transport": clean_config.get("type") or ("stdio" if clean_config.get("command") else "unknown"),
                }

        source_urls = [
            value
            for value in [
                manifest.get("homepage"),
                manifest.get("repository"),
                interface.get("websiteURL"),
            ]
            if value
        ]
        servers.append(
            ServerRecord(
                provider=PROVIDER,
                server_id=plugin_name,
                native_surface="plugin",
                name=interface.get("displayName") or manifest.get("name") or plugin_name,
                description=description,
                capabilities=capabilities,
                source_urls=source_urls,
                transport=transport,
                tools=tools,
                metadata={
                    "marketplace": redact_secrets(entry),
                    "app_manifest": redact_secrets(app_manifest),
                    "mcp_servers": redact_secrets(mcp_servers),
                    "discovery": discovery,
                },
            )
        )
    return servers

