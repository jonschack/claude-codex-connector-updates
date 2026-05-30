from __future__ import annotations
import json, os
from typing import List
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from ..context import CollectContext
from ..utils import USER_AGENT
from ..netguard import max_response_bytes, read_capped
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "smithery"
BASE = "https://registry.smithery.ai/servers"  # VERIFY field names against live API


def _fetch_with_auth(url: str, key: str, timeout: int = 20):
    """Fetch URL with Bearer auth. Returns (text_or_none, meta_dict)."""
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
    })
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = read_capped(resp, max_response_bytes())
            charset = resp.headers.get_content_charset() or "utf-8"
            return body.decode(charset, "replace"), {
                "url": url,
                "status": getattr(resp, "status", None),
                "error": "",
            }
    except HTTPError as exc:
        return None, {"url": url, "status": exc.code, "error": str(exc)}
    except (URLError, TimeoutError, OSError) as exc:
        return None, {"url": url, "status": None, "error": str(exc)}


def collect_smithery(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_SMITHERY_URL", BASE)
    key = os.environ.get("MCP_NEWSLETTER_SMITHERY_KEY", "")
    if not key:
        ctx.add_issue(PROVIDER, base, "MCP_NEWSLETTER_SMITHERY_KEY not set; skipping collector", severity="info")
        return []

    max_servers = int(os.environ.get("MCP_NEWSLETTER_SMITHERY_MAX", "20000"))
    entries: List[RawRegistryEntry] = []
    page = 1
    while len(entries) < max_servers and not ctx.skip_network:
        url = f"{base}?page={page}&pageSize=100"
        throttle(urlparse(url).hostname or "")
        text, meta = _fetch_with_auth(url, key)
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error")))
            break
        ctx.save_raw_text(PROVIDER, f"page-{page}", text, ext="json")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        servers = data.get("servers", [])  # VERIFY field names against live API
        if not servers:
            break
        for s in servers:
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=s.get("qualifiedName", "") or s.get("id", ""),  # VERIFY field names against live API
                name=s.get("displayName", "") or s.get("name", ""),
                description=s.get("description", ""),
                repo_url=s.get("repository", "") or s.get("githubUrl", ""),
                remote_url=s.get("deploymentUrl", "") or s.get("remoteUrl", ""),
                tags=list(s.get("tags", []) or []),
                source_url=base,
            ))
        total = data.get("pagination", {}).get("total", 0)  # VERIFY field names against live API
        if len(entries) >= total or len(servers) < 100:
            break
        page += 1
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, base, "network skipped")
    return entries
