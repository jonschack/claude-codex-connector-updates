from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set

from .models import ServerRecord

# Phase 2 novelty signal — a first-class "is this capability notable?" score that
# is INDEPENDENT of write/read. Drives `notable_capability` events for objective
# (b) (teaching/highlights), separate from the write-capability deltas objective
# (a) emits. Weights are tunable; the score is transparent (component-summed).

DEFAULT_WEIGHTS: Dict[str, float] = {
    "verified": 0.4,    # has at least one observed-schema tool
    "write": 0.2,       # self-reported write capability
    "tools": 0.2,       # tool richness (capped)
    "first_seen": 0.2,  # never seen before
}


def significance_score(server: ServerRecord, seen_before: bool, weights: Optional[Dict[str, float]] = None) -> float:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}  # merge so partial overrides are safe
    score = 0.0
    if server.write_confidence == "high":
        score += w["write"]
    elif server.write_confidence == "medium":
        score += w["write"] * 0.6
    if any(t.capability_tier == "verified_tools" or t.input_schema for t in server.tools):
        score += w["verified"]
    if server.tools:
        score += w["tools"] * min(1.0, len(server.tools) / 5.0)
    if not seen_before:
        score += w["first_seen"]
    return round(max(0.0, min(1.0, score)), 3)


def is_notable(score: float, threshold: float = 0.5) -> bool:
    return score >= threshold


def notable_events(
    servers: List[ServerRecord],
    seen_ids: Set[str],
    threshold: float = 0.5,
    weights: Optional[Dict[str, float]] = None,
    per_source_cap: int = 25,
) -> List[Dict[str, object]]:
    """Emit a `notable_capability` event for each NEW (provider/server_id not in
    seen_ids) server whose significance clears the threshold.

    To avoid a flood when a brand-new large rich source first appears, any
    provider contributing more than `per_source_cap` notable servers in one run
    is collapsed to a single `notable_source` aggregate plus its top-cap items.
    Deterministic: sorted by score desc then identity."""
    per_provider: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for server in servers:
        key = f"{server.provider}/{server.server_id}"
        seen = key in seen_ids
        score = significance_score(server, seen, weights)
        if not seen and is_notable(score, threshold):
            per_provider[server.provider].append({
                "event_type": "notable_capability",
                "provider": server.provider,
                "server_id": server.server_id,
                "name": server.name,
                "score": score,
                "write_confidence": server.write_confidence,
                "tool_count": len(server.tools),
            })
    events: List[Dict[str, object]] = []
    for provider in sorted(per_provider):
        items = sorted(per_provider[provider], key=lambda e: (-e["score"], e["server_id"]))
        if len(items) > per_source_cap:
            events.append({
                "event_type": "notable_source",
                "provider": provider,
                "count": len(items),
                "name": f"{len(items)} new notable capabilities from {provider}",
                "score": 1.0,
            })
            events.extend(items[:per_source_cap])
        else:
            events.extend(items)
    events.sort(key=lambda e: (-float(e.get("score") or 0.0), e["provider"], e.get("server_id", "")))
    return events
