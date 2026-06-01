from __future__ import annotations
import json, os
from typing import List
from urllib.parse import urlparse
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "glama"
BASE = "https://glama.ai/api/mcp/v1/servers"
SOURCE_URL = "https://glama.ai/mcp/servers"

# MCP_NEWSLETTER_GLAMA_DETAIL_CAP — opt-in per-server detail fetch.
# Default 0 = OFF (no-op).  Set >0 to attempt fetching the per-server detail
# endpoint (/api/mcp/v1/servers/{id}) for up to CAP write-candidate servers and
# fold real tool names into their description.
#
# NOTE (2026-05-31): Live probing of 500+ servers shows that the detail endpoint
# exists (HTTP 200) but returns tools[] = [] for every server, identical to the
# list endpoint.  The knob is therefore present but no-op until Glama begins
# populating per-server tool data.  See docs/analysis-protocol/PLAN.md,
# "Source verification status — Glama detail endpoint".
_DETAIL_URL = BASE + "/{server_id}"


def collect_glama(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_GLAMA_URL", BASE)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_GLAMA_MAX", "25000"))
    detail_cap = int(os.environ.get("MCP_NEWSLETTER_GLAMA_DETAIL_CAP", "0"))
    entries: List[RawRegistryEntry] = []
    cursor = ""
    page = 0
    seen_cursors: set = set()
    while len(entries) < max_servers:
        if ctx.skip_network:
            ctx.add_issue(PROVIDER, base, "network skipped")
            break
        url = base + "?first=100" + (f"&after={cursor}" if cursor else "")
        throttle(urlparse(url).hostname or "")
        text, meta = fetch_text(url)
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

        for s in servers:
            repo = (s.get("repository") or {})
            tags = list(s.get("attributes") or [])
            namespace = s.get("namespace", "")
            slug = s.get("slug", "") or s.get("id", "")
            source_id = f"{namespace}/{slug}" if namespace else slug
            description = s.get("description", "")
            tools = s.get("tools") or []
            if tools:
                tool_names = ", ".join(t.get("name", "") for t in tools[:20] if t.get("name"))
                if tool_names:
                    description = description + "  Tools: " + tool_names
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=source_id,
                name=s.get("name", ""),
                description=description,
                repo_url=repo.get("url", "") if isinstance(repo, dict) else "",
                tags=tags,
                source_url=SOURCE_URL,
                raw={"glama_id": s.get("id", "")},  # for the verified /servers/{id} detail URL
            ))

        page_info = data.get("pageInfo", {})
        if not (isinstance(page_info, dict) and page_info.get("hasNextPage")):
            break
        new_cursor = page_info.get("endCursor", "")
        if not new_cursor or new_cursor in seen_cursors:
            break
        seen_cursors.add(new_cursor)
        cursor = new_cursor
        page += 1

    # --- opt-in per-server detail fetch (MCP_NEWSLETTER_GLAMA_DETAIL_CAP > 0) ---
    # For up to detail_cap write-candidate entries (those whose description already
    # contains a write-implying keyword), fetch the per-server detail endpoint and
    # fold any tool names found into the entry's description, matching the existing
    # "  Tools: ..." format.  Guarded by skip_network; throttled per hostname.
    if detail_cap > 0 and not ctx.skip_network:
        _WRITE_KEYWORDS = (
            "write", "creat", "updat", "delet", "modif", "send", "post",
            "remov", "insert", "execut", "publish", "push",
        )
        candidates = [
            e for e in entries
            if any(kw in (e.description or "").lower() for kw in _WRITE_KEYWORDS)
               and "Tools:" not in (e.description or "")
        ][:detail_cap]
        for entry in candidates:
            # Use the verified detail URL form /servers/{id} (the live probe found
            # the namespace/slug variant 404s; only the id-based URL returns 200).
            glama_id = (entry.raw or {}).get("glama_id", "")
            if not glama_id:
                continue
            detail_url = base.rstrip("/") + "/" + glama_id
            throttle(urlparse(detail_url).hostname or "")
            d_text, d_meta = fetch_text(detail_url)
            if not d_text:
                continue
            try:
                d_data = json.loads(d_text)
            except json.JSONDecodeError:
                continue
            tools = d_data.get("tools") or []
            if tools:
                tool_names = ", ".join(
                    t.get("name", "") for t in tools[:20] if t.get("name")
                )
                if tool_names:
                    entry.description = entry.description + "  Tools: " + tool_names

    return entries
