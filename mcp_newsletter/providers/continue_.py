from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "continue"
URL = "https://hub.continue.dev/api/blocks?type=mcpServer"  # VERIFY


def collect_continue(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CONTINUE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "blocks")
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid blocks JSON")
        return []
    items = data.get("blocks") if isinstance(data, dict) else data
    servers = []
    for item in items or []:
        name = item.get("name") or item.get("title") or ""
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""), source_urls=[url],
        ))
    return servers
