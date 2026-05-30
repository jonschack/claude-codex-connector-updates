from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "vscode"
URL = "https://raw.githubusercontent.com/microsoft/mcp/main/registry.json"  # VERIFY exact gallery URL


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
    for item in (data.get("servers") or data if isinstance(data, list) else data.get("servers", [])):
        name = item.get("name") or item.get("displayName") or ""
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""),
            source_urls=[item.get("repository", ""), url],
            remote_url=item.get("url", ""),
        ))
    return servers
