from __future__ import annotations
import os, re
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import html_to_text, slugify

PROVIDER = "cloudflare"
URL = "https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers/"  # VERIFY


def collect_cloudflare(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CLOUDFLARE_URL", URL)
    markup = ctx.fetch(PROVIDER, url, "remote-mcp-servers")
    if not markup:
        return []
    servers = []
    # rows like:  Name | https://<server>.mcp.cloudflare.com/sse
    for name, remote in re.findall(r"([A-Za-z0-9 ]+)\s*\|\s*(https?://[^\s|<]+)", html_to_text(markup)):
        name = name.strip()
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, source_urls=[url], remote_url=remote.strip(),
        ))
    return servers
