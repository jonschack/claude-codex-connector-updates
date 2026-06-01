from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "vscode"
URL = "https://raw.githubusercontent.com/microsoft/mcp/main/registry.json"  # VERIFY: 404 as of 2026-06; microsoft/mcp is a C# SDK repo, no registry.json exists; real source is VS Code Extension Marketplace POST API (tag-based, no simple JSON URL)


def collect_vscode(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_VSCODE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "gallery")
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid gallery JSON")
        return []
    servers = []
    items = data if isinstance(data, list) else (data.get("servers") or [])
    for item in items:
        name = item.get("name") or item.get("displayName") or ""
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""),
            source_urls=[u for u in (item.get("repository", ""), url) if u],
            remote_url=item.get("url", ""),
        ))
    return servers
