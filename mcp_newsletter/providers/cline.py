from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "cline"
# Real marketplace API discovered from Cline's extension source (apps/vscode/src/config.ts).
# Returns a JSON array of server objects (199 items as of 2026-06).
# Requires User-Agent: cline-vscode-extension to avoid 401.
# The older raw.githubusercontent.com/cline/mcp-marketplace/main/marketplace.json URL
# was a planned-but-never-created file; the actual repo contains only a README.
URL = "https://api.cline.bot/v1/mcp/marketplace"
_CLINE_UA = "cline-vscode-extension"


def collect_cline(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CLINE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "marketplace", extra_headers={"User-Agent": _CLINE_UA})
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid marketplace JSON")
        return []
    # API returns a top-level JSON array; each item has mcpId, name, description, githubUrl
    items = data if isinstance(data, list) else (data.get("items") or [])
    servers = []
    for item in items or []:
        name = item.get("name", "")
        if not name:
            continue
        github = item.get("githubUrl", "") or ""
        servers.append(ServerRecord(
            provider=PROVIDER,
            server_id=slugify(name),
            native_surface="connector",
            name=name,
            description=item.get("description", ""),
            source_urls=[u for u in (github, url) if u],
        ))
    return servers
