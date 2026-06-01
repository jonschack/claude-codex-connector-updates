from __future__ import annotations
import json, os
from typing import List, Tuple, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from ..context import CollectContext
from ..utils import USER_AGENT
from ..netguard import max_response_bytes, read_capped
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "pulsemcp"
BASE = "https://api.pulsemcp.com/v0.1/servers"

# VERIFY: real field names confirmed only at generic-registry-spec level; live response unverified pending an API key


def _fetch_with_auth(url: str, key: str, tenant: str = "", timeout: int = 20) -> Tuple[Optional[str], dict]:
    """Fetch URL with X-API-Key auth. Returns (text_or_none, meta_dict)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": key,
    }
    if tenant:
        headers["X-Tenant-ID"] = tenant
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


def collect_pulsemcp(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_PULSEMCP_URL", BASE)
    key = os.environ.get("MCP_NEWSLETTER_PULSEMCP_KEY", "")
    if not key:
        ctx.add_issue(PROVIDER, base, "MCP_NEWSLETTER_PULSEMCP_KEY not set; skipping collector", severity="info")
        return []

    tenant = os.environ.get("MCP_NEWSLETTER_PULSEMCP_TENANT", "")
    max_servers = int(os.environ.get("MCP_NEWSLETTER_PULSEMCP_MAX", "25000"))
    entries: List[RawRegistryEntry] = []
    cursor = ""
    page = 0
    seen_cursors: set = set()

    while len(entries) < max_servers:
        if ctx.skip_network:
            ctx.add_issue(PROVIDER, base, "network skipped")
            break
        url = base + (f"?cursor={cursor}" if cursor else "")
        throttle(urlparse(url).hostname or "")
        text, meta = _fetch_with_auth(url, key, tenant)
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error")))
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

        for entry in servers:
            # Generic Registry spec: each item may be wrapped {"server":{...},"_meta":{...}}
            server = entry.get("server") or entry
            entry_meta = entry.get("_meta") or {}
            # Skip if any meta value is a dict with status == "deleted"
            if any(
                isinstance(v, dict) and v.get("status") == "deleted"
                for v in entry_meta.values()
            ):
                continue
            name = server.get("name", "")
            repo = server.get("repository") or {}
            remotes = server.get("remotes") or []
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=name,
                official_name=name,
                name=server.get("title") or name.split("/")[-1] or name,
                description=server.get("description", ""),
                repo_url=repo.get("url", "") if isinstance(repo, dict) else "",
                subpath=repo.get("subfolder", "") if isinstance(repo, dict) else "",
                remote_url=(remotes[0].get("url", "") if remotes else ""),
                tags=list((server.get("_meta") or {}).get("tags", [])),
                source_url=base,
                raw=entry,
            ))

        new_cursor = (data.get("metadata") or {}).get("nextCursor")
        if not new_cursor or new_cursor in seen_cursors:
            break
        seen_cursors.add(new_cursor)
        cursor = new_cursor
        page += 1

    return entries
