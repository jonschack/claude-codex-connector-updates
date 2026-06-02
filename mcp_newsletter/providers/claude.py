from __future__ import annotations

import os
import re
from typing import List

from ..content_extract import extract_main_text
from ..context import CollectContext
from ..fetch_rendered import fetch_rendered
from ..models import ServerRecord
from ..utils import env_bool, extract_links, extract_title, html_to_text, slugify


PROVIDER = "claude"
DIRECTORY_URL = "https://claude.com/connectors"


def _maybe_rendered_links(ctx: CollectContext, directory_url: str, links: List[str]) -> List[str]:
    """Phase 1b hook: the directory is a client-rendered SPA, so a plain fetch
    sees only a fraction of connectors. When a render backend is configured
    (MCP_NEWSLETTER_CLAUDE_RENDER=1 + MCP_NEWSLETTER_RENDER_BACKEND), merge any
    extra detail links the rendered DOM exposes. No-op by default."""
    if ctx.skip_network or not env_bool("MCP_NEWSLETTER_CLAUDE_RENDER"):
        return links
    rendered, meta = fetch_rendered(directory_url)
    if rendered:
        return sorted(set(links) | set(extract_links(rendered, directory_url)))
    if meta.get("error"):
        ctx.add_issue(PROVIDER, directory_url, f"rendered directory fetch: {meta['error']}")
    return links


def _capabilities_from_text(text: str) -> List[str]:
    lowered = text.lower()
    caps: List[str] = []
    if "read & write" in lowered or "read and write" in lowered:
        caps.append("Read & write")
    elif re.search(r"\bwrite\b", lowered):
        caps.append("Write")
    if re.search(r"\bread\b", lowered):
        caps.append("Read")
    if "interactive" in lowered:
        caps.append("Interactive")
    return caps


def _capabilities_from_markup(markup: str, text: str) -> List[str]:
    values = []
    for match in re.finditer(r'fs-list-field=["\']capabilities["\'][^>]*>(.*?)</div>', markup, flags=re.I | re.S):
        value = html_to_text(match.group(1)).strip()
        if value:
            values.append(value)
    if values:
        return sorted(set(values))
    return _capabilities_from_text(text)


def collect_claude(ctx: CollectContext) -> List[ServerRecord]:
    directory_url = os.environ.get("MCP_NEWSLETTER_CLAUDE_CONNECTORS_URL", DIRECTORY_URL)
    directory = ctx.fetch(PROVIDER, directory_url, "connectors-directory")
    if not directory:
        return []

    links = _maybe_rendered_links(ctx, directory_url, extract_links(directory, directory_url))
    detail_urls = sorted(
        {
            link.split("#", 1)[0].rstrip("/")
            for link in links
            if re.match(r"https://claude\.com/(?:[a-z]{2}/)?connectors/[a-z0-9-]+/?$", link)
        }
    )
    if not detail_urls:
        ctx.add_issue(PROVIDER, directory_url, "No connector detail links found; using directory page as a single catalog record")
        text = extract_main_text(directory)
        return [
            ServerRecord(
                provider=PROVIDER,
                server_id="connectors-directory",
                native_surface="connector",
                name="Claude connectors directory",
                description=text[:500],
                capabilities=_capabilities_from_text(text),
                source_urls=[directory_url],
            )
        ]

    servers: List[ServerRecord] = []
    for url in detail_urls[: ctx.max_details]:
        markup = ctx.fetch(PROVIDER, url, f"connector-{url.rsplit('/', 1)[-1]}")
        if not markup:
            continue
        text = extract_main_text(markup)
        slug = slugify(url.rsplit("/", 1)[-1])
        title = extract_title(markup, fallback=slug).replace(" | Claude", "").strip()
        servers.append(
            ServerRecord(
                provider=PROVIDER,
                server_id=slug,
                native_surface="connector",
                name=title or slug,
                description=text[:1000],
                capabilities=_capabilities_from_markup(markup, text),
                source_urls=[url, directory_url],
                metadata={"catalog_text_hash_source": "detail_page"},
            )
        )
    return servers
