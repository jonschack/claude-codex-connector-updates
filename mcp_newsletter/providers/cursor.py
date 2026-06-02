from __future__ import annotations

import os
from typing import List

from ..context import CollectContext
from ..fetch_rendered import firecrawl_map
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "cursor"
# cursor.directory rebuilt on the "Open Plugins" model and sits behind Vercel
# Attack Challenge Mode (the old /mcp 429). Plain HTTP (incl. sitemap.xml) is
# challenge-gated; Firecrawl /map bypasses it and cheaply enumerates all plugin
# URLs (~2,284 with "mcp" in the slug). Requires FIRECRAWL_API_KEY; without it
# the collector skips gracefully (info issue), like the keyed registry sources.
SITE = "https://cursor.directory"


def _name_from_slug(slug: str) -> str:
    parts = slug.split("-")
    cleaned = [p for p in parts if p.lower() != "mcp"] or parts
    return " ".join(cleaned).title()


def collect_cursor(ctx: CollectContext) -> List[ServerRecord]:
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, SITE, "network fetch skipped by configuration")
        return []
    site = os.environ.get("MCP_NEWSLETTER_CURSOR_URL", SITE)
    raw_limit = os.environ.get("MCP_NEWSLETTER_CURSOR_MAX", "5000")
    limit = int(raw_limit) if raw_limit.strip().isdigit() else 5000
    urls, meta = firecrawl_map(site, limit=limit)
    if not urls:
        ctx.add_issue(
            PROVIDER, site,
            f"cursor enumeration unavailable: {meta.get('error') or 'no urls'} "
            "(directory is JS/challenge-gated; needs FIRECRAWL_API_KEY)",
            severity="info" if "FIRECRAWL_API_KEY" in (meta.get("error") or "") else "warning",
        )
        return []
    # Filter plugin URLs whose slug contains "mcp" (a substring heuristic — high
    # recall for a coverage monitor; may include a few false positives like
    # "compose-mcp"). Dedup by server_id so case/fragment variants collapse.
    by_id = {}
    for raw in urls:
        clean = raw.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if "/plugins/" not in clean:
            continue
        slug = clean.rsplit("/", 1)[-1]
        if "mcp" not in slug.lower():
            continue
        by_id.setdefault(slugify(slug), (slug, clean))
    servers: List[ServerRecord] = []
    for server_id in sorted(by_id):
        slug, url = by_id[server_id]
        servers.append(ServerRecord(
            provider=PROVIDER,
            server_id=server_id,
            native_surface="connector",
            name=_name_from_slug(slug),
            description="",
            source_urls=[url],
            transport="catalog",
        ))
    return servers
