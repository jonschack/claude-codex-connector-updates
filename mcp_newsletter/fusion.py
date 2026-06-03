from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .classifier import EVIDENCE_TIER_RANK
from .identity import canonical_repo

# Phase 4 fusion: every tier (registry, declared_manifest, npm/pypi package watch,
# github momentum, grok radar) cross-links on the ONE canonical normalizer
# (identity.canonical_repo), so URL variants of the same repo collapse to a single
# row. Corroboration = how many DISTINCT evidence tiers independently attest the
# write capability — engagement-only sources (grok virality) are excluded from
# that count (they're traction, not evidence).


@dataclass
class FusedRecord:
    key: str                                  # canonical repo (or fallback id)
    tiers: set = field(default_factory=set)   # distinct evidence tiers seen
    sources: set = field(default_factory=set)  # provenance labels (incl. engagement)
    urls: set = field(default_factory=set)     # every variant URL seen

    @property
    def corroboration(self) -> int:
        """Distinct evidence tiers attesting (engagement-only excluded)."""
        return len(self.tiers)

    @property
    def best_tier(self) -> str:
        return max(self.tiers, key=lambda t: EVIDENCE_TIER_RANK.get(t, 0), default="none")


# Sources that are traction signals, not write evidence — excluded from corroboration.
ENGAGEMENT_SOURCES = {"grok", "engagement", "viral"}


def fuse(items: List[dict]) -> Dict[str, FusedRecord]:
    """Collapse items sharing a canonical repo into one FusedRecord. Each item:
    {url, tier, source}. `tier` is an evidence tier (or "none"); `source` is a
    provenance label. URL variants (.git, /tree/main, www., scheme, case) collapse
    via canonical_repo. Items with no resolvable repo are keyed by their raw url/
    source so they aren't all merged into one bucket."""
    out: Dict[str, FusedRecord] = {}
    for item in items:
        url = item.get("url", "")
        key = canonical_repo(url) or f"{item.get('source', '')}:{url}"
        rec = out.get(key)
        if rec is None:
            rec = FusedRecord(key=key)
            out[key] = rec
        source = item.get("source", "")
        tier = item.get("tier", "none")
        rec.sources.add(source)
        if url:
            rec.urls.add(url)
        # engagement-only sources corroborate visibility, not the write claim
        if source not in ENGAGEMENT_SOURCES and tier and tier != "none":
            rec.tiers.add(tier)
    return out
