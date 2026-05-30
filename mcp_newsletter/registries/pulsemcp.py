from __future__ import annotations
import json, os
from typing import List
from urllib.parse import urlparse
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "pulsemcp"
BASE = "https://api.pulsemcp.com/v0beta/servers"  # VERIFY field names against live API


def collect_pulsemcp(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_PULSEMCP_URL", BASE)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_PULSEMCP_MAX", "20000"))
    entries, offset = [], 0
    while len(entries) < max_servers and not ctx.skip_network:
        url = f"{base}?count_per_page=100&offset={offset}"
        throttle(urlparse(url).hostname or "")
        text, meta = fetch_text(url)
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error")))
            break
        ctx.save_raw_text(PROVIDER, f"page-{offset}", text, ext="json")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        servers = data.get("servers", [])  # VERIFY field names against live API
        if not servers:
            break
        for s in servers:
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=s.get("name", ""),  # VERIFY field names against live API
                name=s.get("name", ""),
                description=s.get("short_description", "") or s.get("description", ""),
                repo_url=s.get("source_code_url", "") or s.get("github_url", ""),
                remote_url=s.get("remote_url", "") or "",
                tags=list(s.get("categories", []) or []),
                source_url=base,
            ))
        if not data.get("next") and len(servers) < 100:
            break
        offset += 100
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, base, "network skipped")
    return entries
