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
BASE = "https://registry.smithery.ai/servers"


def _fetch(url: str, key: str = "", timeout: int = 20):
    """Fetch URL. If key is non-empty, sends Authorization: Bearer header.
    Returns (text_or_none, meta_dict).
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = Request(url, headers=headers)
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
    # Public by default — no key required.
    max_servers = int(os.environ.get("MCP_NEWSLETTER_SMITHERY_MAX", "20000"))

    if ctx.skip_network:
        ctx.add_issue(PROVIDER, base, "network skipped")
        return []

    entries: List[RawRegistryEntry] = []
    page = 1
    seen_pages: set = set()

    while len(entries) < max_servers:
        if page in seen_pages:
            break
        seen_pages.add(page)

        url = f"{base}?page={page}&pageSize=100"
        throttle(urlparse(url).hostname or "")
        text, meta = _fetch(url, key)
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error") or meta.get("status")))
            break
        ctx.save_raw_text(PROVIDER, f"page-{page}", text, ext="json")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        servers = data.get("servers", [])
        if not servers:
            break
        for s in servers:
            qualified = s.get("qualifiedName", "") or s.get("id", "")
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=qualified,
                name=s.get("displayName", "") or qualified,
                description=s.get("description", ""),
                repo_url="",
                remote_url="",
                tags=[],
                source_url=s.get("homepage", "") or "https://smithery.ai/servers",
                raw={
                    "useCount": s.get("useCount"),
                    "verified": s.get("verified"),
                    "remote": s.get("remote"),
                },
            ))
            if len(entries) >= max_servers:
                break

        pagination = data.get("pagination", {})
        current_page = pagination.get("currentPage", page)
        total_pages = pagination.get("totalPages", 1)
        if current_page >= total_pages:
            break
        page = current_page + 1

    return entries
