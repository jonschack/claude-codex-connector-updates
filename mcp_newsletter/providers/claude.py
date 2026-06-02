from __future__ import annotations

import os
import re
import time
from typing import List

from ..content_extract import extract_main_text
from ..context import CollectContext
from ..fetch_rendered import fetch_rendered
from ..models import ServerRecord
from ..utils import env_bool, extract_links, extract_title, html_to_text, slugify


PROVIDER = "claude"
DIRECTORY_URL = "https://claude.com/connectors"

# The directory is a Webflow CMS list paginated server-side via a hashed param
# (e.g. ?cc61befa_page=2). Plain HTTP across those pages returns the FULL catalog
# (~338), vs ~24 from page 1 alone — no JS rendering needed. The param hash can
# change if the site is rebuilt, so we discover it from the page rather than hardcode.
CONNECTOR_RE = re.compile(r"https://claude\.com/(?:[a-z]{2}/)?connectors/[a-z0-9-]+/?$")
PAGE_PARAM_RE = re.compile(r"[?&]([a-z0-9]+_page)=\d+")
SAFETY_MAX_PAGES = 60


def _connector_links(markup: str, base_url: str) -> set:
    return {
        link.split("#", 1)[0].rstrip("/")
        for link in extract_links(markup, base_url)
        if CONNECTOR_RE.match(link)
    }


def _collect_detail_urls(ctx: CollectContext, directory_url: str, first_markup: str) -> List[str]:
    """All connector detail URLs, following Webflow CMS pagination until a page
    yields no new connectors (or a safety page cap is hit). Falls back to a render
    backend only when no server-side pagination param is present."""
    urls = _connector_links(first_markup, directory_url)
    match = PAGE_PARAM_RE.search(first_markup)
    if match:
        param = match.group(1)
        for page in range(2, SAFETY_MAX_PAGES + 1):
            markup = ctx.fetch(PROVIDER, f"{directory_url}?{param}={page}", f"connectors-page-{page}")
            if not markup:
                # distinguish a transient fetch failure from a genuinely empty page
                ctx.add_issue(PROVIDER, f"{directory_url}?{param}={page}",
                              f"pagination fetch failed at page {page}; stopping (catalog may be truncated)")
                break
            new = _connector_links(markup, directory_url) - urls
            if not new:
                break
            urls |= new
        else:
            ctx.add_issue(PROVIDER, directory_url, f"hit SAFETY_MAX_PAGES={SAFETY_MAX_PAGES}; pagination may be truncated")
    else:
        # No server-side pagination found — try a render backend if configured.
        urls |= set(_maybe_rendered_links(ctx, directory_url, list(urls)))
    return sorted(urls)


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

    detail_urls = _collect_detail_urls(ctx, directory_url, directory)
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
    # Fetch all paginated detail pages (full catalog ~338). Safety-capped via env.
    # Optional inter-request delay for politeness (default 0; fetch_text already
    # backs off on 429/Retry-After, so this is extra courtesy for large crawls).
    max_details = int(os.environ.get("MCP_NEWSLETTER_CLAUDE_MAX_DETAILS", "1000"))
    delay_ms = int(os.environ.get("MCP_NEWSLETTER_CLAUDE_DETAIL_DELAY_MS", "0") or "0")
    for url in detail_urls[:max_details]:
        markup = ctx.fetch(PROVIDER, url, f"connector-{url.rsplit('/', 1)[-1]}")
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
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
