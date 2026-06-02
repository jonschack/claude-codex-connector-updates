from __future__ import annotations

from typing import List

from ..context import CollectContext
from ..models import ServerRecord

PROVIDER = "vscode"
# RETIRED (2026-06): VS Code's MCP gallery is backed by api.mcp.github.com, a
# curated SUBSET of the official MCP registry the pipeline already ingests in the
# registry tier (source `official`, registry.modelcontextprotocol.io). No unique
# vendor data — retiring avoids duplicate coverage mislabeled as a vendor surface.
# (Optionally add api.mcp.github.com as a thin registry-tier source later.)


def collect_vscode(ctx: CollectContext) -> List[ServerRecord]:
    ctx.add_issue(
        PROVIDER,
        "https://api.mcp.github.com/v0/servers",
        "retired: VS Code gallery is a curated subset of the official MCP registry (already in the registry tier)",
        severity="info",
    )
    return []
