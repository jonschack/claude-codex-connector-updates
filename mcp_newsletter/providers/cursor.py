from __future__ import annotations
import os, re
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import extract_github_repos, html_to_text, slugify

PROVIDER = "cursor"
URL = "https://cursor.directory/mcp"  # VERIFY


def collect_cursor(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CURSOR_URL", URL)
    markup = ctx.fetch(PROVIDER, url, "mcp-directory")
    if not markup:
        return []
    servers = []
    seen_slugs: set = set()
    # Parse per-card: each card is a block containing a heading + description + optional repo link
    for card_match in re.finditer(
        r'<div[^>]*class="[^"]*mcp-card[^"]*"[^>]*>(.*?)</div\s*>',
        markup,
        flags=re.I | re.S,
    ):
        block = card_match.group(1)
        # Extract card title from h2 or h3
        title_match = re.search(r"<h[23][^>]*>(.*?)</h[23]>", block, flags=re.I | re.S)
        name = html_to_text(title_match.group(1)).strip() if title_match else ""
        if not name:
            continue
        slug = slugify(name)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        # Extract card-local description (paragraph text)
        desc_match = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.I | re.S)
        description = html_to_text(desc_match.group(1)).strip() if desc_match else ""
        # Extract repo links local to this card
        repos = extract_github_repos(block)
        source = repos[:1] + [url] if repos else [url]
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slug, native_surface="connector",
            name=name, description=description, source_urls=source,
        ))
    # Sort deterministically by name
    servers.sort(key=lambda s: s.name)
    if markup and not servers:
        ctx.add_issue(PROVIDER, url, "no records parsed; DOM may have changed")
    return servers
