from __future__ import annotations

import os
import re
from typing import List

from ..context import CollectContext
from ..models import ServerRecord
from ..utils import html_to_text, slugify

PROVIDER = "openai"
DIRECTORY_URL = "https://platform.openai.com/docs/connectors"  # VERIFY: 404 as of 2026-06; "connectors" renamed to "apps" (2025-12-17); no public app/connector directory found


def _capabilities(text: str) -> List[str]:
    lowered = text.lower()
    caps = []
    if "read and write" in lowered or "read & write" in lowered:
        caps.append("Read & write")
    elif re.search(r"\bwrite\b|\bsend\b|\bcreate\b", lowered):
        caps.append("Write")
    if re.search(r"\bread\b|\bsearch\b", lowered):
        caps.append("Read")
    return caps


def collect_openai(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_OPENAI_URL", DIRECTORY_URL)
    markup = ctx.fetch(PROVIDER, url, "connectors-directory")
    if not markup:
        return []
    servers: List[ServerRecord] = []
    for match in re.finditer(r'<div class="connector">(.*?)</div>', markup, flags=re.I | re.S):
        block = match.group(1)
        title = re.search(r"<h3[^>]*>(.*?)</h3>", block, flags=re.I | re.S)
        name = html_to_text(title.group(1)).strip() if title else ""
        if not name:
            continue
        text = html_to_text(block)
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=text[:500], capabilities=_capabilities(text),
            source_urls=[url],
        ))
    if markup and not servers:
        ctx.add_issue(PROVIDER, url, "no records parsed; DOM may have changed")
    return servers
