from __future__ import annotations
import os
from typing import List
from urllib.parse import urlparse
from ..context import CollectContext
from ..utils import extract_github_repos, fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "github_servers"
README_URL = "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/README.md"


def collect_github_servers(ctx: CollectContext) -> List[RawRegistryEntry]:
    url = os.environ.get("MCP_NEWSLETTER_GITHUB_SERVERS_URL", README_URL)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, url, "network skipped")
        return []
    throttle(urlparse(url).hostname or "")
    text, meta = fetch_text(url)
    if not text:
        ctx.add_issue(PROVIDER, url, str(meta.get("error")))
        return []
    ctx.save_raw_text(PROVIDER, "readme", text, ext="md")
    entries = []
    for repo in extract_github_repos(text):
        name = repo.rstrip("/").split("/")[-1]
        # monorepo: the reference servers live under modelcontextprotocol/servers
        subpath = ""
        entries.append(RawRegistryEntry(
            source=PROVIDER, source_id=repo, name=name,
            repo_url=repo, subpath=subpath, source_url=url,
        ))
    return entries
