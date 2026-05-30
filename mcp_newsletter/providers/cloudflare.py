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
    # html_to_text flattens to a single space-separated line (no newlines).
    # Match a URL preceded by "|" and look back for a short identifier name
    # (no sentence-ending punctuation, at most 5 space-separated words).
    text = html_to_text(markup)
    for m in re.finditer(
        r"([A-Za-z0-9][A-Za-z0-9 ._-]{0,40}?)\s*\|\s*(https?://\S+)",
        text,
    ):
        raw_name = m.group(1).strip()
        remote = m.group(2).strip()
        # Reject names that contain sentence-ending punctuation — they have leaked prose
        if re.search(r"[.!?]", raw_name):
            # Fall back: take only the last word-run after the last punctuation
            clean = re.split(r"[.!?]\s*", raw_name)[-1].strip()
            raw_name = clean
        name = raw_name.strip()
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, source_urls=[url], remote_url=remote,
        ))
    if markup and not servers:
        ctx.add_issue(PROVIDER, url, "no records parsed; DOM may have changed")
    return servers
