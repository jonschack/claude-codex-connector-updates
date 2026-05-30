from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry

PROVIDER = "glama"
BASE = "https://glama.ai/api/mcp/v1/servers"  # VERIFY field names against live API


def collect_glama(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_GLAMA_URL", BASE)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_GLAMA_MAX", "20000"))
    entries: List[RawRegistryEntry] = []
    cursor = ""
    page = 0
    seen_cursors: set = set()
    while len(entries) < max_servers and not ctx.skip_network:
        url = base + (f"?after={cursor}" if cursor else "")
        text, meta = fetch_text(url)
        ctx.save_raw_text(PROVIDER, f"page-{page}", text or "", ext="json")
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error")))
            break
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        servers = data.get("servers", [])  # VERIFY field names against live API
        if not servers:
            break

        for s in servers:
            repo = (s.get("repository") or {})  # VERIFY field names against live API
            tags = list(s.get("attributes", {}).get("tags", []) or s.get("tags", []))
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=s.get("id", "") or s.get("slug", ""),
                name=s.get("name", ""),
                description=s.get("description", ""),
                repo_url=repo.get("url", "") if isinstance(repo, dict) else "",
                tags=tags,
                source_url=base,
            ))
        page_info = data.get("pageInfo", {})  # VERIFY field names against live API
        cursor = page_info.get("endCursor", "") if isinstance(page_info, dict) else ""
        page += 1
        if not cursor:
            break
        if cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, base, "network skipped")
    return entries
