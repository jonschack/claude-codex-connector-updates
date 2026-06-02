from __future__ import annotations

from typing import List

from ..context import CollectContext
from ..models import ServerRecord

PROVIDER = "continue"
# RETIRED (2026-06): the public bulk MCP-blocks list is gone — hub.continue.dev
# redirects to www, /explore is auth-gated, and the search API is capped at 5
# type-blind results. Per-block getFromSlug works but there is no public way to
# ENUMERATE the catalog. These community blocks are covered by the registry tier.


def collect_continue(ctx: CollectContext) -> List[ServerRecord]:
    ctx.add_issue(
        PROVIDER,
        "https://hub.continue.dev",
        "retired: no public bulk MCP-server list since the 2026 hub restructure (explore auth-gated, search capped at 5)",
        severity="info",
    )
    return []
