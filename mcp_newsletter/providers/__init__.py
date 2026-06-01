from __future__ import annotations

from typing import List

from ..context import CollectContext
from ..models import ServerRecord
from .claude import collect_claude
from .cline import collect_cline
from .cloudflare import collect_cloudflare
from .codex import collect_codex
from .continue_ import collect_continue
from .cursor import collect_cursor
from .gemini import collect_gemini
from .grok import collect_grok
from .openai import collect_openai
from .vscode import collect_vscode


def collect_all(ctx: CollectContext) -> List[ServerRecord]:
    servers: List[ServerRecord] = []
    for collector in (
        collect_codex, collect_gemini, collect_claude, collect_grok,
        collect_openai, collect_cursor, collect_vscode, collect_cline,
        collect_continue, collect_cloudflare,
    ):
        try:
            servers.extend(collector(ctx))
        except Exception as exc:  # Keep one provider failure from breaking the daily run.
            ctx.add_issue(getattr(collector, "__name__", "provider"), "collector", repr(exc), severity="error")
    return servers

