from __future__ import annotations
import json
import os
import re
from typing import List
from urllib.parse import urlparse
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "mcpso"
URL = "https://mcp.so/servers"

# GitHub / GitLab repo URL prefix patterns
_REPO_PREFIXES = ("https://github.com/", "http://github.com/",
                  "https://gitlab.com/", "http://gitlab.com/")


def _is_repo_url(url: str) -> bool:
    return any(url.startswith(p) for p in _REPO_PREFIXES)


def _parse_tags(raw) -> List[str]:
    """Normalise a tags value that may be a list, a comma-string, or a JSON string."""
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw or raw in ("[]", "null"):
            return []
        # JSON-encoded list e.g. '["a","b"]'
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(t).strip() for t in parsed if str(t).strip()]
            except (json.JSONDecodeError, ValueError):
                pass
        # Comma-separated string
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _extract_servers_from_blob(blob: str) -> List[dict]:
    """Extract unique server objects (have a real 'uuid' key) from the RSC blob."""
    servers = {}
    for m in re.finditer(r'"uuid"', blob):
        idx = m.start()
        # Walk back to find the opening { that contains this uuid key
        search_start = max(0, idx - 8000)
        region = blob[search_start:idx]
        depth = 0
        obj_open = None
        for i in range(len(region) - 1, -1, -1):
            c = region[i]
            if c == "}":
                depth += 1
            elif c == "{":
                if depth == 0:
                    obj_open = search_start + i
                    break
                else:
                    depth -= 1
        if obj_open is None:
            continue
        # Scan forward to find the matching closing }
        depth = 0
        end_pos = None
        scan_end = min(obj_open + 8000, len(blob))
        for i, c in enumerate(blob[obj_open:scan_end]):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end_pos = obj_open + i + 1
                    break
        if not end_pos:
            continue
        try:
            obj = json.loads(blob[obj_open:end_pos])
        except (json.JSONDecodeError, ValueError):
            continue
        uuid = obj.get("uuid")
        if uuid and isinstance(uuid, str) and uuid not in servers:
            servers[uuid] = obj
    return list(servers.values())


def collect_mcpso(ctx: CollectContext) -> List[RawRegistryEntry]:
    url = os.environ.get("MCP_NEWSLETTER_MCPSO_URL", URL)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, url, "network skipped")
        return []
    throttle(urlparse(url).hostname or "")
    text, meta = fetch_text(url)
    if not text:
        ctx.add_issue(PROVIDER, url, str(meta.get("error")))
        return []
    ctx.save_raw_text(PROVIDER, "servers", text, ext="html")

    # --- Extract RSC chunks ---
    raw_chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', text)
    blob = ""
    for chunk in raw_chunks:
        try:
            blob += json.loads('"' + chunk + '"')
        except (json.JSONDecodeError, ValueError):
            continue  # skip malformed chunk

    # --- Extract server objects ---
    server_objs = _extract_servers_from_blob(blob)

    if not server_objs:
        ctx.add_issue(PROVIDER, url,
                      "no servers parsed from RSC payload; page structure may have changed")
        return []

    entries: List[RawRegistryEntry] = []
    for s in server_objs:
        name = s.get("name") or ""
        title = s.get("title") or ""
        display_name = title or name
        if not display_name and not s.get("url"):
            continue  # junk record

        description = s.get("description") or ""

        # Fold inline tool names into description (like glama/official pattern)
        tools_raw = s.get("tools")
        if isinstance(tools_raw, list):
            tools_list = tools_raw
        elif isinstance(tools_raw, str) and tools_raw.startswith("["):
            try:
                tools_list = json.loads(tools_raw)
            except (json.JSONDecodeError, ValueError):
                tools_list = []
        else:
            tools_list = []  # RSC ref string like "$2a" — ignore

        if isinstance(tools_list, list) and tools_list:
            tool_names = ", ".join(
                t.get("name", "") for t in tools_list[:20]
                if isinstance(t, dict) and t.get("name")
            )
            if tool_names:
                description = description + "  Tools: " + tool_names

        raw_url = s.get("url") or ""
        repo_url = raw_url if _is_repo_url(raw_url) else ""
        tags = _parse_tags(s.get("tags"))
        uuid = s.get("uuid") or name

        entries.append(RawRegistryEntry(
            source=PROVIDER,
            source_id=uuid,
            name=display_name,
            description=description,
            repo_url=repo_url,
            tags=tags,
            source_url=url,
            raw={"mcpso_id": s.get("id"), "is_official": s.get("is_official")},
        ))

    return entries
