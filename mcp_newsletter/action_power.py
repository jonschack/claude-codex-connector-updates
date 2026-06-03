from __future__ import annotations

from typing import List

from .action_class import action_classes_for, record_action_classes
from .registries.base import RegistryServerRecord

# P2-lite action POWER tier: how much blast radius a write has, derived from the
# action CLASS (action_class.py). Ordinal high>medium>low. A server's power is the
# MAX over its classes — power is the most consequential thing it can do. P3 refines
# this per-tool from schema + annotations and swaps in the full score.
POWER_BY_CLASS = {
    "money": "high",
    "comms": "high",
    "deploy": "high",
    "system_control": "high",
    "data_write": "medium",
    "social": "medium",
    "scheduling": "medium",
    "other": "low",
}
POWER_RANK = {"low": 0, "medium": 1, "high": 2}


def _max_power(classes: List[str]) -> str:
    best = "low"
    for cls in classes:
        tier = POWER_BY_CLASS.get(cls, "low")
        if POWER_RANK[tier] > POWER_RANK[best]:
            best = tier
    return best


def power_tier_for(text: str) -> str:
    """Power tier from free text (server/tool description)."""
    return _max_power(action_classes_for(text))


def record_power_tier(rec: RegistryServerRecord) -> str:
    """Power tier for a server, from its description/tags/tool names."""
    return _max_power(record_action_classes(rec))
