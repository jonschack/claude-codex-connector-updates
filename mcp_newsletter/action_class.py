from __future__ import annotations

import re
from typing import Dict, List

from .classifier import evidence_tier
from .registries.base import RegistryServerRecord

# Minimal keyword action-CLASS taxonomy (the *domain* of the action, distinct from
# action POWER which P3 refines). Used for per-action-class coverage telemetry so
# blind spots are visible (e.g. "0% of system_control verified") rather than hidden
# inside an aggregate. A server may match several classes; it's counted in each.
ACTION_CLASS_KEYWORDS: Dict[str, List[str]] = {
    "money": ["pay", "payment", "invoice", "charge", "refund", "transfer", "wallet",
              "crypto", "trade", "trading", "checkout", "billing", "stripe", "transaction"],
    "comms": ["email", "message", "slack", "sms", "reply", "notify", "chat",
              "whatsapp", "mail", "discord", "telegram", "send"],
    "deploy": ["deploy", "release", "publish", "ship", "rollout", "provision",
               "kubernetes", "k8s", "terraform", "vercel", "netlify"],
    "system_control": ["shell", "exec", "execute", "command", "sudo", "filesystem",
                       "process", "ssh", "terminal", "bash", "script", "kill"],
    "data_write": ["create", "update", "delete", "insert", "write", "database",
                   "sql", "record", "document", "upload", "save", "edit", "modify"],
    "social": ["tweet", "twitter", "instagram", "linkedin", "follow", "like",
               "share", "social", "post"],
    "scheduling": ["calendar", "schedule", "event", "meeting", "booking",
                   "reminder", "appointment"],
}

_CLASS_RES = {
    name: re.compile(r"\b(" + "|".join(re.escape(k) for k in kws) + r")\b", re.I)
    for name, kws in ACTION_CLASS_KEYWORDS.items()
}


def action_classes_for(text: str) -> List[str]:
    """Action classes whose keywords appear in `text` (order stable), or
    `["other"]` if none match."""
    hits = [name for name, rx in _CLASS_RES.items() if rx.search(text or "")]
    return hits or ["other"]


def record_action_classes(rec: RegistryServerRecord) -> List[str]:
    """Action classes for a server, drawn from its description, tags, and the
    names/descriptions of its (write) tools."""
    blob = " ".join([
        rec.description or "",
        " ".join(rec.tags or []),
        # tool names are snake_case; split on `_` so `deploy_service` matches `deploy`
        " ".join(f"{t.name.replace('_', ' ')} {t.description}" for t in rec.tools),
    ])
    return action_classes_for(blob)


def coverage_by_action_class(records: Dict[str, RegistryServerRecord]) -> Dict[str, Dict[str, int]]:
    """Per action class, count write-signal records by evidence tier (plus a
    `total`). Records with no write evidence (tier `none`) are excluded — coverage
    is about what we know can write. Shape: {class: {tier: n, ..., 'total': n}}."""
    cov: Dict[str, Dict[str, int]] = {}
    for rec in records.values():
        tier = evidence_tier(rec.evidence)
        if tier == "none":
            continue
        for cls in record_action_classes(rec):
            bucket = cov.setdefault(cls, {})
            bucket[tier] = bucket.get(tier, 0) + 1
            bucket["total"] = bucket.get("total", 0) + 1
    return cov
