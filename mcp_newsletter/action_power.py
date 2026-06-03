from __future__ import annotations

from typing import List, Tuple

from .action_class import action_classes_for, record_action_classes
from .models import ToolRecord
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
    """Power tier for a server, from its description/tags/tool names (keyword)."""
    return _max_power(record_action_classes(rec))


def _bump(tier: str) -> str:
    return {"low": "medium", "medium": "high", "high": "high"}[tier]


def tool_power(tool: ToolRecord) -> Tuple[str, str]:
    """(power_tier, confidence) for a single write tool. Power from the tool's
    name + description + schema text. Confidence is `high` when grounded in the
    actual schema/annotations (not just keywords). A destructive + open-world
    tool is the highest blast radius, so it bumps one tier within its band (P3)."""
    schema_text = " ".join(str(k) for k in (tool.input_schema or {}).keys())
    tier = _max_power(action_classes_for(f"{tool.name} {tool.description} {schema_text}"))
    ann = tool.annotations or {}
    grounded = bool(ann) or bool(tool.input_schema)
    if ann.get("destructiveHint") is True and ann.get("openWorldHint") is True:
        tier = _bump(tier)
    return tier, ("high" if grounded else "low")


def record_power(rec: RegistryServerRecord) -> Tuple[str, str]:
    """(power_tier, confidence) for a server. Power = MAX over its verified write
    tools (the most consequential thing it can do), confidence taken from the tool
    that sets the tier. Falls back to a low-confidence keyword read when no tools
    have been captured (emerging/claimed servers)."""
    if not rec.tools:
        return record_power_tier(rec), "low"
    best_tier, best_conf = "low", "low"
    for tool in rec.tools:
        tier, conf = tool_power(tool)
        if POWER_RANK[tier] > POWER_RANK[best_tier]:
            best_tier, best_conf = tier, conf
        elif tier == best_tier and conf == "high":
            best_conf = "high"
    return best_tier, best_conf
