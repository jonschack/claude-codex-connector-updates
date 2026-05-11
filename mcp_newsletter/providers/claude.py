from __future__ import annotations

import os
import re
from typing import List

from ..context import CollectContext
from ..models import ServerRecord
from ..utils import extract_links, extract_title, html_to_text, slugify


PROVIDER = "claude"
DIRECTORY_URL = "https://claude.com/connectors"


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

    links = extract_links(directory, directory_url)
    detail_urls = sorted(
        {
            link.split("#", 1)[0].rstrip("/")
            for link in links
            if re.match(r"https://claude\.com/(?:[a-z]{2}/)?connectors/[a-z0-9-]+/?$", link)
        }
    )
    if not detail_urls:
        ctx.add_issue(PROVIDER, directory_url, "No connector detail links found; using directory page as a single catalog record")
        text = html_to_text(directory)
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
        text = html_to_text(markup)
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
