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
    text = html_to_text(markup)
    servers = []
    for repo in extract_github_repos(markup):
        name = repo.rstrip("/").split("/")[-1]
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=text[:300], source_urls=[repo, url],
        ))
    return servers
