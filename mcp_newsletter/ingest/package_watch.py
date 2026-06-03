from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import List

from ..registries.base import RawRegistryEntry

# P4 widen-recall: watch package registries so a new MCP server is seen the moment
# it's published — often BEFORE any aggregator indexes it. npm via the search
# endpoint (the legacy replicate _changes feed was deprecated 2025-05-29), PyPI via
# the newest-packages RSS. New package -> a `claimed` candidate + repo cross-link
# (so fusion corroborates it against the registry/grok tiers).

_MCP_HINT = "mcp"


def _is_mcp(name: str, description: str, keywords: List[str]) -> bool:
    blob = f"{name} {description} {' '.join(keywords)}".lower()
    return _MCP_HINT in blob


def parse_npm_search(json_text: str) -> List[RawRegistryEntry]:
    """Parse registry.npmjs.org/-/v1/search results into claimed candidates,
    filtered to MCP packages."""
    try:
        data = json.loads(json_text or "")
    except (json.JSONDecodeError, TypeError):
        return []
    out: List[RawRegistryEntry] = []
    for obj in (data.get("objects") if isinstance(data, dict) else None) or []:
        pkg = obj.get("package") or {}
        name = pkg.get("name", "")
        if not name:
            continue
        keywords = pkg.get("keywords") or []
        description = pkg.get("description", "")
        if not _is_mcp(name, description, keywords):
            continue
        # Only the repository link becomes the canonical key — a homepage URL
        # would mis-link the fusion identity, so it's deliberately not a fallback.
        repo = (pkg.get("links") or {}).get("repository") or ""
        out.append(RawRegistryEntry(
            source="npm", source_id=name, name=name, description=description,
            repo_url=repo, tags=list(keywords), last_updated=pkg.get("date", ""),
            source_url="https://www.npmjs.com/package/" + name,
        ))
    return out


def parse_pypi_rss(xml_text: str) -> List[RawRegistryEntry]:
    """Parse PyPI's newest-packages RSS into claimed candidates, filtered to MCP."""
    try:
        root = ET.fromstring((xml_text or "").strip())
    except ET.ParseError:
        return []
    out: List[RawRegistryEntry] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        # PyPI titles look like "package-name 1.2.3"; take the package name.
        name = title.split(" ")[0] if title else ""
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not name or not _is_mcp(name, description, []):
            continue
        out.append(RawRegistryEntry(
            source="pypi", source_id=name, name=name, description=description,
            source_url=link, last_updated=(item.findtext("pubDate") or "").strip(),
        ))
    return out
