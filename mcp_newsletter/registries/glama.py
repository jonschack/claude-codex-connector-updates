from __future__ import annotations
import json, os
from typing import List
from urllib.parse import urlparse
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "glama"
BASE = "https://glama.ai/api/mcp/v1/servers"
SOURCE_URL = "https://glama.ai/mcp/servers"


def collect_glama(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_GLAMA_URL", BASE)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_GLAMA_MAX", "25000"))
    entries: List[RawRegistryEntry] = []
    cursor = ""
    page = 0
    seen_cursors: set = set()
    while len(entries) < max_servers:
        if ctx.skip_network:
            ctx.add_issue(PROVIDER, base, "network skipped")
            break
        url = base + "?first=100" + (f"&after={cursor}" if cursor else "")
        throttle(urlparse(url).hostname or "")
        text, meta = fetch_text(url)
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error")))
            break
        ctx.save_raw_text(PROVIDER, f"page-{page}", text, ext="json")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        servers = data.get("servers", [])
        if not servers:
            break

        for s in servers:
            repo = (s.get("repository") or {})
            tags = list(s.get("attributes") or [])
            namespace = s.get("namespace", "")
            slug = s.get("slug", "") or s.get("id", "")
            source_id = f"{namespace}/{slug}" if namespace else slug
            description = s.get("description", "")
            tools = s.get("tools") or []
            if tools:
                tool_names = ", ".join(t.get("name", "") for t in tools[:20] if t.get("name"))
                if tool_names:
                    description = description + "  Tools: " + tool_names
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=source_id,
                name=s.get("name", ""),
                description=description,
                repo_url=repo.get("url", "") if isinstance(repo, dict) else "",
                tags=tags,
                source_url=SOURCE_URL,
            ))

        page_info = data.get("pageInfo", {})
        if not (isinstance(page_info, dict) and page_info.get("hasNextPage")):
            break
        new_cursor = page_info.get("endCursor", "")
        if not new_cursor or new_cursor in seen_cursors:
            break
        seen_cursors.add(new_cursor)
        cursor = new_cursor
        page += 1
    return entries
