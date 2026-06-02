from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional


# Conservative per-source expected-minimum floors. A previously-healthy source
# returning far below its floor (or zero) is treated as broken, not empty.
# Vendor tier (per-provider) and registry tier are evaluated separately so a
# vendor-only health pass never falsely flags a registry source as "empty".
# NOTE: raise `claude` once P1 rendered collection captures the full directory.
VENDOR_FLOORS: Dict[str, int] = {
    "claude": 300,  # full Webflow-pagination collection lands ~338 (was ~24 pre-pagination)
    "codex": 1,
    "gemini": 50,
    "cline": 50,
    "cloudflare": 5,
    # currently-broken collectors keep a floor of 1 so they flag "empty" loudly
    # until Phase 1b repairs them, without dragging the run red on a soft miss.
    "grok": 1,
    "openai": 1,
    "cursor": 1,
    "vscode": 1,
    "continue": 1,
}

REGISTRY_FLOORS: Dict[str, int] = {
    "official": 100,
    "glama": 1000,
    "docker": 50,
    "smithery": 100,
    "mcpso": 10,
    "github_servers": 5,
}

DEFAULT_FLOORS: Dict[str, int] = {**VENDOR_FLOORS, **REGISTRY_FLOORS}


def floors_from_env(defaults: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """Floors, with per-source env overrides MCP_NEWSLETTER_HEALTH_FLOOR_<SOURCE>."""
    floors = dict(defaults if defaults is not None else DEFAULT_FLOORS)
    for source in list(floors):
        raw = os.environ.get(f"MCP_NEWSLETTER_HEALTH_FLOOR_{source.upper()}")
        if raw and raw.strip().isdigit():
            floors[source] = int(raw.strip())
    return floors


@dataclass
class SourceHealth:
    source: str
    count: int
    floor: int
    status: str  # "ok" | "degraded" | "empty"
    message: str


def evaluate_source_health(counts: Dict[str, int], floors: Dict[str, int]) -> List[SourceHealth]:
    """Classify each source by this-run record count vs its floor.

    Sources with no configured floor only flag when genuinely empty (floor 1).
    """
    sources = sorted(set(counts) | set(floors))
    out: List[SourceHealth] = []
    for source in sources:
        count = int(counts.get(source, 0))
        floor = int(floors.get(source, 1))
        if count <= 0:
            status = "empty"
            message = f"{source}: collected 0 (floor {floor}) — source likely broken"
        elif count < floor:
            status = "degraded"
            message = f"{source}: {count} < floor {floor} — partial/stale collection"
        else:
            status = "ok"
            message = f"{source}: {count} (floor {floor})"
        out.append(SourceHealth(source=source, count=count, floor=floor, status=status, message=message))
    return out


def run_drop_alert(total_now: int, total_prev: Optional[int], threshold_pct: float) -> Optional[str]:
    """Return an alert string if the run-over-run total dropped >= threshold_pct."""
    if not total_prev or total_prev <= 0:
        return None
    drop = (total_prev - total_now) / total_prev * 100.0
    if drop >= threshold_pct:
        return (
            f"total records dropped {drop:.0f}% "
            f"({total_prev} -> {total_now}, threshold {threshold_pct:.0f}%)"
        )
    return None


def summarize_health(
    counts: Dict[str, int],
    floors: Dict[str, int],
    total_now: int,
    total_prev: Optional[int],
    drop_pct: float,
) -> Dict[str, object]:
    """Roll per-source health + run-drop into a status block with an alert line."""
    statuses = evaluate_source_health(counts, floors)
    bad = [s for s in statuses if s.status != "ok"]
    drop = run_drop_alert(total_now, total_prev, drop_pct)
    degraded = bool(bad) or drop is not None
    alert: Optional[str] = None
    if degraded:
        parts = [s.message for s in bad]
        if drop:
            parts.append(drop)
        alert = "PIPELINE DEGRADED: " + "; ".join(parts)
    return {
        "degraded": degraded,
        "alert": alert,
        "sources": [s.__dict__ for s in statuses],
    }
