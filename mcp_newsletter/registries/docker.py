from __future__ import annotations
import json, os, re
from typing import List
from urllib.parse import urlparse
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry
from . import throttle

PROVIDER = "docker"
CONTENTS_API = "https://api.github.com/repos/docker/mcp-registry/contents/servers"
RAW = "https://raw.githubusercontent.com/docker/mcp-registry/main/servers/{name}/server.yaml"


def _yaml_scalar(text: str, key: str) -> str:
    """Extract a scalar value for a top-level or single-indented key.
    Matches lines like ``key: value`` (any indentation).
    """
    m = re.search(rf"^\s*{re.escape(key)}:\s*(.+)$", text, flags=re.M)
    return m.group(1).strip().strip('"\'') if m else ""


def _yaml_nested(text: str, parent: str, child: str) -> str:
    """Extract a scalar value from a nested YAML block (parent → child).
    Handles the real docker/mcp-registry server.yaml shape, e.g.::

        source:
          project: https://...
        about:
          description: Some text
    """
    m = re.search(
        rf"^{re.escape(parent)}:\s*\n(?:[ \t]+\S[^\n]*\n)*?[ \t]+{re.escape(child)}:\s*(.+)$",
        text, flags=re.M,
    )
    return m.group(1).strip().strip('"\'') if m else ""


def _yaml_list(text: str, parent: str, child: str) -> List[str]:
    """Extract a list of scalar items under parent → child.
    Handles the shape::

        meta:
          tags:
            - item1
            - item2
    """
    # Find the child key inside the parent block
    m = re.search(
        rf"^{re.escape(parent)}:\s*\n((?:[ \t]+[^\n]+\n)*)",
        text, flags=re.M,
    )
    if not m:
        return []
    block = m.group(1)
    list_m = re.search(rf"[ \t]+{re.escape(child)}:\s*\n((?:[ \t]+-[^\n]+\n?)*)", block)
    if not list_m:
        return []
    return [
        re.sub(r"^\s*-\s*", "", line).strip()
        for line in list_m.group(1).splitlines()
        if re.match(r"^\s*-", line)
    ]


def collect_docker(ctx: CollectContext) -> List[RawRegistryEntry]:
    listing_url = os.environ.get("MCP_NEWSLETTER_DOCKER_URL", CONTENTS_API)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, listing_url, "network skipped")
        return []
    throttle(urlparse(listing_url).hostname or "")
    text, meta = fetch_text(listing_url)
    if not text:
        ctx.add_issue(PROVIDER, listing_url, str(meta.get("error")))
        return []
    ctx.save_raw_text(PROVIDER, "listing", text, ext="json")
    try:
        listing = json.loads(text)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, listing_url, "invalid listing JSON")
        return []
    entries = []
    for item in listing:
        if item.get("type") != "dir":
            continue
        name = item.get("name")
        if not name:
            continue
        yurl = RAW.format(name=name)
        throttle(urlparse(yurl).hostname or "")
        ybody, ymeta = fetch_text(yurl)
        if not ybody:
            ctx.add_issue(PROVIDER, yurl, str(ymeta.get("error") or ymeta.get("status")))
            continue
        ctx.save_raw_text(PROVIDER, f"{name}-server", ybody, ext="yaml")
        # Real field layout (docker/mcp-registry as of 2026-05):
        #   about.description, about.title
        #   source.project   (repo URL for local servers)
        #   remote.url       (endpoint URL for remote servers)
        #   meta.category    (scalar)
        #   meta.tags        (YAML list)
        description = _yaml_nested(ybody, "about", "description")
        repo_url = _yaml_nested(ybody, "source", "project")
        remote_url = _yaml_nested(ybody, "remote", "url")
        category = _yaml_nested(ybody, "meta", "category")
        tags = _yaml_list(ybody, "meta", "tags")
        if category and category not in tags:
            tags = [category] + tags
        entries.append(RawRegistryEntry(
            source=PROVIDER, source_id=name, name=name,
            description=description,
            repo_url=repo_url,
            remote_url=remote_url,
            tags=tags,
            source_url=yurl,
        ))
    return entries
