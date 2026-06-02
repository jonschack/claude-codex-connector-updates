from __future__ import annotations

from typing import List

from ..context import CollectContext
from ..models import ServerRecord

PROVIDER = "openai"
# RETIRED (2026-06): OpenAI's "connectors" were renamed to "apps" and folded into
# the ChatGPT App Directory (chatgpt.com/apps), which is Cloudflare/JS-gated with
# no public machine-readable source. The only remnant is an ~8-item static
# connector_id list in the MCP guide (low value, overlaps Grok + registry tier).
# Disabled to stop silent breakage; revisit if a public app-directory API ships.


def collect_openai(ctx: CollectContext) -> List[ServerRecord]:
    ctx.add_issue(
        PROVIDER,
        "https://chatgpt.com/apps",
        "retired: ChatGPT app directory is JS/Cloudflare-gated; no public machine-readable source",
        severity="info",
    )
    return []
