# registry tier
from __future__ import annotations

import os
import time
from typing import Callable, Dict, List

from ..context import CollectContext
from .base import RawRegistryEntry, RegistryCollection


_LAST_HOST_HIT: Dict[str, float] = {}


def throttle(host: str) -> None:
    interval = float(os.environ.get("MCP_NEWSLETTER_REGISTRY_HOST_THROTTLE", "0.2"))
    last = _LAST_HOST_HIT.get(host, 0.0)
    now = time.monotonic()
    wait = interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_HOST_HIT[host] = time.monotonic()


def enabled_sources() -> List[str]:
    allow = os.environ.get("MCP_NEWSLETTER_REGISTRIES", "")
    all_sources = ["official", "github_servers", "docker", "pulsemcp", "smithery", "glama", "mcpso"]
    if not allow.strip():
        return all_sources
    wanted = {s.strip() for s in allow.split(",") if s.strip()}
    return [s for s in all_sources if s in wanted]


def collect_all_registries(ctx: CollectContext) -> RegistryCollection:
    from .official import collect_official
    from .github_servers import collect_github_servers
    from .docker import collect_docker
    from .pulsemcp import collect_pulsemcp
    from .smithery import collect_smithery
    from .glama import collect_glama
    from .mcpso import collect_mcpso

    registry = {
        "official": collect_official,
        "github_servers": collect_github_servers,
        "docker": collect_docker,
        "pulsemcp": collect_pulsemcp,
        "smithery": collect_smithery,
        "glama": collect_glama,
        "mcpso": collect_mcpso,
    }
    budget = float(os.environ.get("MCP_NEWSLETTER_REGISTRY_TIME_BUDGET_SEC", "1800"))
    started = time.monotonic()
    collection = RegistryCollection()
    for name in enabled_sources():
        if time.monotonic() - started > budget:
            ctx.add_issue(name, "time-budget",
                          f"skipped: run exceeded {budget:.0f}s time budget", severity="warning")
            collection.source_ok[name] = False  # not run -> freezes liveness (no false delist)
            continue
        collector = registry[name]
        try:
            entries = collector(ctx)
            collection.entries.extend(entries)
            collection.source_ok[name] = True
        except Exception as exc:  # one source failing must not break the run
            ctx.add_issue(name, "registry-collector", repr(exc), severity="error")
            collection.source_ok[name] = False
    return collection
