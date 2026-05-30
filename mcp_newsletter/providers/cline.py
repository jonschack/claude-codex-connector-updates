from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "cline"
URL = "https://raw.githubusercontent.com/cline/mcp-marketplace/main/marketplace.json"  # VERIFY


def collect_cline(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CLINE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "marketplace")
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid marketplace JSON")
        return []
    items = data.get("items") if isinstance(data, dict) else data
    servers = []
    for item in items or []:
        name = item.get("name", "")
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""),
            source_urls=[item.get("githubUrl", "") or item.get("repo", ""), url],
        ))
    return servers
