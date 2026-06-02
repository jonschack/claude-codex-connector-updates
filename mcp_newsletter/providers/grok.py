from __future__ import annotations

import os
from typing import Dict, List

from ..context import CollectContext
from ..models import ServerRecord
from ..utils import html_to_text, slugify


PROVIDER = "grok"
# The catalog page (/connectors/catalog) and news page are dead (404/403). The
# live, plain-HTTP, server-rendered markdown source is /grok/connectors.md, which
# documents the BUILT-IN connectors. The larger third-party catalog lives only in
# the auth-gated grok.com app with no public machine-readable source, so this
# collector intentionally captures the documented built-ins (~8) only.
DOC_URLS = [
    "https://docs.x.ai/grok/connectors.md",
]

KNOWN_CONNECTORS = {
    "gmail-google-calendar": ["Gmail", "Google Calendar"],
    "google-drive": ["Google Drive"],
    "onedrive": ["OneDrive"],
    "outlook": ["Outlook Mail", "Outlook Calendar", "Outlook"],
    "microsoft-teams": ["Microsoft Teams", "Teams"],
    "sharepoint": ["SharePoint"],
    "salesforce": ["Salesforce"],
    "custom-mcp": ["Custom MCP", "MCP server"],
}


def _context_window(text: str, terms: List[str], radius: int = 320) -> str:
    lowered = text.lower()
    for term in terms:
        idx = lowered.find(term.lower())
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(text), idx + radius)
            return text[start:end].strip()
    return ""


def collect_grok(ctx: CollectContext) -> List[ServerRecord]:
    urls = [url.strip() for url in os.environ.get("MCP_NEWSLETTER_GROK_URLS", ",".join(DOC_URLS)).split(",") if url.strip()]
    source_texts: Dict[str, str] = {}
    for url in urls:
        markup = ctx.fetch(PROVIDER, url, url)
        if markup:
            source_texts[url] = html_to_text(markup)

    combined = "\n".join(source_texts.values())
    if not combined:
        return []

    servers: List[ServerRecord] = []
    for server_id, terms in KNOWN_CONNECTORS.items():
        if not any(term.lower() in combined.lower() for term in terms):
            continue
        description = _context_window(combined, terms) or f"Grok connector reference for {', '.join(terms)}"
        source_urls = [url for url, text in source_texts.items() if any(term.lower() in text.lower() for term in terms)]
        servers.append(
            ServerRecord(
                provider=PROVIDER,
                server_id=slugify(server_id),
                native_surface="connector",
                name=terms[0],
                description=description,
                source_urls=source_urls,
                metadata={"matched_terms": terms},
            )
        )
    if not servers:
        servers.append(
            ServerRecord(
                provider=PROVIDER,
                server_id="grok-connectors-docs",
                native_surface="connector",
                name="Grok connectors documentation",
                description=combined[:1000],
                source_urls=list(source_texts),
            )
        )
    return servers

