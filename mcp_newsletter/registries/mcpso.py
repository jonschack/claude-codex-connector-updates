from __future__ import annotations
import os
from typing import List
from ..context import CollectContext
from ..utils import extract_github_repos, fetch_text
from .base import RawRegistryEntry

PROVIDER = "mcpso"
URL = "https://mcp.so/servers"


def collect_mcpso(ctx: CollectContext) -> List[RawRegistryEntry]:
    url = os.environ.get("MCP_NEWSLETTER_MCPSO_URL", URL)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, url, "network skipped")
        return []
    text, meta = fetch_text(url)
    ctx.save_raw_text(PROVIDER, "listing", text or "", ext="html")
    if not text:
        ctx.add_issue(PROVIDER, url, str(meta.get("error")))
        return []
    entries = []
    for repo in extract_github_repos(text):
        name = repo.rstrip("/").split("/")[-1]
        entries.append(RawRegistryEntry(source=PROVIDER, source_id=repo, name=name,
                                        repo_url=repo, source_url=url))
    return entries
