from __future__ import annotations
import os, re
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "cloudflare"
# Markdown source for Cloudflare's own MCP servers page (stable .md URL).
# URL changed from /mcp-servers/ to /mcp-servers-for-cloudflare/ in 2026.
URL = "https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/index.md"


def _parse_markdown(text: str, source_url: str) -> List[ServerRecord]:
    """Parse Cloudflare's MCP servers markdown page.

    The page has two forms of server records:
      1. The main Cloudflare API MCP server listed in a JSON snippet inside a code block.
      2. A product-specific table: | [Name ↗](github-url) | Description | https://xxx.mcp.cloudflare.com/mcp |

    We extract both forms.
    """
    servers: List[ServerRecord] = []
    seen: set = set()

    def _add(name: str, description: str, remote: str) -> None:
        slug = slugify(name)
        if slug in seen:
            return
        seen.add(slug)
        servers.append(ServerRecord(
            provider=PROVIDER,
            server_id=slug,
            native_surface="connector",
            name=name,
            description=description,
            source_urls=[source_url],
            remote_url=remote,
            transport="remote",
        ))

    # --- Form 1: main Cloudflare API MCP server URL from JSON snippet ---
    api_url_match = re.search(r'"url"\s*:\s*"(https://mcp\.cloudflare\.com/[^"]+)"', text)
    if api_url_match:
        _add("Cloudflare API", "Access the entire Cloudflare API over 2,500 endpoints", api_url_match.group(1))

    # --- Form 2: product-specific table rows ---
    # Each row: | [Name text ↗](github-url) | Description text | https://xxx.mcp.cloudflare.com/mcp |
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "https://" not in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 3:
            continue
        # Extract name from markdown link [Name ↗](...)
        name_match = re.search(r"\[([^\]]+?)\s*↗?\]", parts[0])
        if not name_match:
            continue
        name = name_match.group(1).strip()
        if not name:
            continue
        description = re.sub(r"\[.*?\]\(.*?\)", "", parts[1]).strip()
        # URL is the last column — strip any trailing whitespace/pipe
        remote = parts[2].strip().rstrip("|").strip()
        if not re.match(r"https://", remote):
            continue
        _add(name, description, remote)

    return servers


def collect_cloudflare(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CLOUDFLARE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "mcp-servers-for-cloudflare")
    if not body:
        return []
    servers = _parse_markdown(body, url)
    if body and not servers:
        ctx.add_issue(PROVIDER, url, "no records parsed; page structure may have changed")
    return servers
