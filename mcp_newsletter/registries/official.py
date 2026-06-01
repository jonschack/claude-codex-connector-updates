# mcp_newsletter/registries/official.py
from __future__ import annotations

import json
import os
from typing import List
from urllib.parse import urlparse

from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "official"
BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def collect_official(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_OFFICIAL_URL", BASE_URL)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_OFFICIAL_MAX", "20000"))
    candidates: List[tuple] = []  # (is_latest, RawRegistryEntry)
    cursor = ""
    page = 0
    while len(candidates) < max_servers:
        url = base + (f"?cursor={cursor}" if cursor else "")
        if ctx.skip_network:
            ctx.add_issue(PROVIDER, url, "network skipped")
            break
        throttle(urlparse(url).hostname or "")
        text, meta = fetch_text(url)
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error") or meta.get("status")))
            break
        ctx.save_raw_text(PROVIDER, f"page-{page}", text, ext="json")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        for entry in data.get("servers", []):
            # Real API wraps each record: {"server": {...}, "_meta": {...}}.
            server = entry.get("server") or entry
            entry_meta = entry.get("_meta") or {}
            official_meta = entry_meta.get("io.modelcontextprotocol.registry/official") or {}
            if official_meta.get("status") == "deleted":
                continue
            name = server.get("name", "")
            is_latest = official_meta.get("isLatest")
            repo = (server.get("repository") or {})
            remotes = server.get("remotes") or []
            candidates.append((is_latest, RawRegistryEntry(
                source=PROVIDER,
                source_id=name,
                official_name=name,
                name=server.get("title") or name.split("/")[-1] or name,
                description=server.get("description", ""),
                repo_url=repo.get("url", ""),
                subpath=repo.get("subfolder", "") or "",
                remote_url=(remotes[0].get("url", "") if remotes else ""),
                tags=list((server.get("_meta") or {}).get("tags", [])),
                last_updated=official_meta.get("updatedAt", ""),
                source_url=base,
                raw=entry,
            )))
        cursor = (data.get("metadata") or {}).get("nextCursor")
        page += 1
        if not cursor:
            break
    # Keep only the isLatest version per server when any version is marked latest.
    # For servers with no isLatest flag at all, keep all entries (preserve old behaviour).
    names_with_latest = {e.official_name for is_latest, e in candidates if is_latest is True}
    entries: List[RawRegistryEntry] = [
        e for is_latest, e in candidates
        if not (is_latest is False and e.official_name in names_with_latest)
    ]
    return entries
