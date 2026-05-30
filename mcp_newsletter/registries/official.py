# mcp_newsletter/registries/official.py
from __future__ import annotations

import json
import os
from typing import List

from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry

PROVIDER = "official"
BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def collect_official(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_OFFICIAL_URL", BASE_URL)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_OFFICIAL_MAX", "20000"))
    entries: List[RawRegistryEntry] = []
    cursor = ""
    page = 0
    while len(entries) < max_servers:
        url = base + (f"?cursor={cursor}" if cursor else "")
        if ctx.skip_network:
            ctx.add_issue(PROVIDER, url, "network skipped")
            break
        text, meta = fetch_text(url)
        ctx.save_raw_text(PROVIDER, f"page-{page}", text or "", ext="json")
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error") or meta.get("status")))
            break
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        for server in data.get("servers", []):
            if server.get("status") == "deleted":
                continue
            repo = (server.get("repository") or {})
            remotes = server.get("remotes") or []
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=server.get("name", ""),
                official_name=server.get("name", ""),
                name=server.get("name", "").split("/")[-1] or server.get("name", ""),
                description=server.get("description", ""),
                repo_url=repo.get("url", ""),
                subpath=repo.get("subfolder", "") or "",
                remote_url=(remotes[0].get("url", "") if remotes else ""),
                tags=list((server.get("_meta") or {}).get("tags", [])),
                last_updated=server.get("updated_at", ""),
                source_url=base,
                raw=server,
            ))
        cursor = (data.get("metadata") or {}).get("next_cursor")
        page += 1
        if not cursor:
            break
    return entries
