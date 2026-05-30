# mcp_newsletter/registry_classify.py
from __future__ import annotations

from typing import List

from .classifier import RANK, classify_catalog
from .registries.base import RegistryServerRecord

# Tags/categories that imply the server can take action.
WRITE_TAGS = {
    "write", "automation", "actions", "productivity", "crm", "email",
    "messaging", "calendar", "deploy", "devops", "payments", "ecommerce",
    "project-management", "ticketing", "social",
}


def tags_to_capabilities(tags: List[str]) -> List[str]:
    lowered = {t.strip().lower() for t in tags}
    return ["Write"] if (lowered & WRITE_TAGS) else []


def _max_conf(a: str, b: str) -> str:
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def classify_registry_record(rec: RegistryServerRecord, run_date: str) -> None:
    """Set rec.write_confidence from catalog evidence (tags + capabilities +
    description), combined with any previously stored tool evidence.

    Records the catalog result under confidence_by_source['catalog'] with today's
    date. Tool evidence (confidence_by_source['tools']) is set elsewhere by the
    discovery step; here we only read it so confidence never drops merely because
    tools were not re-discovered this run.
    """
    caps = sorted(set(rec.capabilities) | set(tags_to_capabilities(rec.tags)))
    rec.capabilities = caps
    catalog_conf, evidence = classify_catalog(caps, rec.description)
    rec.confidence_by_source["catalog"] = {"confidence": catalog_conf, "date": run_date}
    rec.evidence = evidence

    effective = "unknown"
    for source in ("catalog", "tools"):
        info = rec.confidence_by_source.get(source)
        if info:
            effective = _max_conf(effective, info["confidence"])
    rec.write_confidence = effective
