from __future__ import annotations

from .action_power import POWER_RANK
from .classifier import EVIDENCE_TIER_RANK
from .registry_discovery import days_between

# Phase 3: the real frontier score. Strictly lexicographic by design —
# (evidence_tier -> action_power -> recency) — implemented with weights spaced so
# a lower band can NEVER overcome a higher one. Classification confidence damps
# the power contribution (a low-confidence high-power read can't masquerade as a
# verified high-power tool). A single bounded "attention" factor (corroboration +
# momentum, capped) only re-orders WITHIN a band. Engagement is never an input —
# viral items are ranked separately, on engagement, in their own section.

_TIER_W = 1000.0      # evidence tier dominates everything (rank 0..4 -> 0..4000)
_POWER_W = 100.0      # power dominates recency/attention (rank 0..2, conf-damped)
_WITHIN_W = 10.0      # recency + attention live here; < the min power step (50)
ATTENTION_CAP = 0.15  # attention re-orders by at most 15% of the within-band range

RECENCY_HORIZON_DAYS = 180.0  # linear freshness decay to 0 over ~6 months
_CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.75, "low": 0.5}


def freshness(recency: str, run_date: str, horizon: float = RECENCY_HORIZON_DAYS) -> float:
    """Source-attested recency as freshness in [0,1]. Unknown/empty -> 0; anything
    older than the horizon -> 0. Because recency is the source-reported timestamp
    (NOT when we first saw write evidence), a tool verified today but published
    long ago scores 0 here — which is exactly the backfill-suppression the spec
    wants (no stale tools masquerading as new)."""
    if not recency:
        return 0.0
    age = days_between(recency[:10], run_date)
    if age >= horizon:
        return 0.0
    return max(0.0, 1.0 - age / horizon)


def _attention(corroboration: int, momentum: float) -> float:
    """Bounded [0,1] attention from corroboration (distinct evidence tiers) and
    momentum (star/release velocity, 0 until P4), collapsed so they aren't
    triple-counted. Capped to ATTENTION_CAP by the caller."""
    corrob = min(1.0, max(0, corroboration - 1) / 3.0)  # 1 tier -> 0, 4+ -> 1
    return min(1.0, 0.6 * corrob + 0.4 * max(0.0, min(1.0, momentum)))


def score(evidence_tier: str, power_tier: str, recency_freshness: float,
          confidence: str, *, corroboration: int = 1, momentum: float = 0.0) -> float:
    """Lexicographic frontier score (higher = closer to the headline)."""
    tier_rank = EVIDENCE_TIER_RANK.get(evidence_tier, 0)
    conf = _CONFIDENCE_FACTOR.get(confidence, 0.5)
    eff_power = POWER_RANK.get(power_tier, 0) * conf       # confidence damps power
    attention = ATTENTION_CAP * _attention(corroboration, momentum)
    within = max(0.0, min(1.0, recency_freshness)) * (1 - ATTENTION_CAP) + attention
    return tier_rank * _TIER_W + eff_power * _POWER_W + within * _WITHIN_W
