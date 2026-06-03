# mcp_newsletter/registry_classify.py
from __future__ import annotations

from typing import List

from .classifier import RANK, WRITE_RE, classify_catalog
from .registries.base import RegistryServerRecord

# Evidence kinds produced by observing the *actual* server (live tool probe in
# registry_discovery, or static manifest parse) — these are gathered by other
# steps and must survive re-classification AND carry across runs (the updater
# seeds them from prior state). Catalog kinds are regenerated each run, so only
# these observed kinds are carried across the merge.
OBSERVED_EVIDENCE_KINDS = {"tool_text", "tool_rollup", "mcp_annotation", "declared_manifest"}


def _evidence_key(item: dict) -> tuple:
    return (item.get("kind"), str(item.get("value")), item.get("confidence"))

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
    if catalog_conf in ("unknown", "low") and WRITE_RE.search(rec.description or ""):
        catalog_conf = "medium"
        evidence = list(evidence) + [{"kind": "registry_description",
                                      "value": "write verb in description",
                                      "confidence": "medium"}]
    rec.confidence_by_source["catalog"] = {"confidence": catalog_conf, "date": run_date}

    # Union-merge: preserve observed evidence (live tool probe / annotations /
    # declared manifest) appended by discovery or carried from prior state, then
    # add this run's freshly-derived catalog evidence under a stable dedup key.
    # (Was `rec.evidence = evidence`, which clobbered annotation/tool evidence —
    # the P1-0 bug that left 0/31,664 records with annotation evidence.)
    merged = [ev for ev in rec.evidence if ev.get("kind") in OBSERVED_EVIDENCE_KINDS]
    seen = {_evidence_key(ev) for ev in merged}
    for ev in evidence:
        key = _evidence_key(ev)
        if key not in seen:
            merged.append(ev)
            seen.add(key)
    rec.evidence = merged

    effective = "unknown"
    for source in ("catalog", "tools", "manifest"):
        info = rec.confidence_by_source.get(source)
        if info:
            effective = _max_conf(effective, info["confidence"])
    rec.write_confidence = effective
