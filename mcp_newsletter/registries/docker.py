from __future__ import annotations
import json, os, re
from typing import List
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry

PROVIDER = "docker"
CONTENTS_API = "https://api.github.com/repos/docker/mcp-registry/contents/servers"
RAW = "https://raw.githubusercontent.com/docker/mcp-registry/main/servers/{name}/server.yaml"


def _yaml_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, flags=re.M)
    return m.group(1).strip().strip('"\'') if m else ""


def collect_docker(ctx: CollectContext) -> List[RawRegistryEntry]:
    listing_url = os.environ.get("MCP_NEWSLETTER_DOCKER_URL", CONTENTS_API)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, listing_url, "network skipped")
        return []
    text, meta = fetch_text(listing_url)
    ctx.save_raw_text(PROVIDER, "listing", text or "", ext="json")
    if not text:
        ctx.add_issue(PROVIDER, listing_url, str(meta.get("error")))
        return []
    try:
        listing = json.loads(text)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, listing_url, "invalid listing JSON")
        return []
    entries = []
    for item in listing:
        if item.get("type") != "dir":
            continue
        name = item["name"]
        yurl = RAW.format(name=name)
        ybody, _ = fetch_text(yurl)
        if not ybody:
            continue
        ctx.save_raw_text(PROVIDER, f"{name}-server", ybody, ext="yaml")
        entries.append(RawRegistryEntry(
            source=PROVIDER, source_id=name, name=name,
            description=_yaml_value(ybody, "longLived") or _yaml_value(ybody, "description"),
            repo_url=_yaml_value(ybody, "source") or _yaml_value(ybody, "repository"),
            tags=[c.strip() for c in _yaml_value(ybody, "category").split(",") if c.strip()],
            source_url=yurl,
        ))
    return entries
