from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .classifier import RANK, evidence_tier
from .mcp_discovery import discover_remote_tools
from .registries.base import RegistryServerRecord

# Cap of write tools persisted per record (keeps state small; P2/P3 read these).
TOP_N_WRITE_TOOLS = 12

# Registry sources treated as authorities (worth probing ahead of aggregators).
AUTHORITY_SOURCES = {"official"}

# Verified/annotation evidence older than this is re-probed (the reserved
# re-verification slice) so the board reflects current behavior (§8 freshness).
DISCOVERY_DECAY_DAYS = 56  # 8 weeks
# Fractions of the cap reserved for exploration and re-verification so neither
# starves under a flood of keyword-claimed candidates.
EXPLORATION_FRACTION = 0.2
REVERIFY_FRACTION = 0.15
_HEADLINE_TIERS = {"verified_tools", "annotation"}


def days_between(a: str, b: str) -> int:
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    except ValueError:
        return 10 ** 6


def _has_authority(rec: RegistryServerRecord) -> bool:
    return any(s.get("source") in AUTHORITY_SOURCES for s in rec.sources)


def is_claimed_write(rec: RegistryServerRecord) -> bool:
    return RANK.get(rec.write_confidence, 0) >= RANK["medium"]


def _needs_reverify(rec: RegistryServerRecord, run_date: str) -> bool:
    """Headline (verified/annotation) record whose last probe is past decay."""
    if evidence_tier(rec.evidence) not in _HEADLINE_TIERS:
        return False
    info = rec.confidence_by_source.get("tools") or {}
    last = info.get("date", "")
    return bool(last) and days_between(last, run_date) >= DISCOVERY_DECAY_DAYS


def select_discovery_candidates(
    records: List[RegistryServerRecord],
    cap: int,
    last_discovered: Dict[str, str],
    cadence_days: int,
    run_date: str,
    new_identities: Optional[Iterable[str]] = None,
) -> List[RegistryServerRecord]:
    """Deterministic, capped, rotating selection of remote servers to probe,
    biased toward the write frontier. Priority buckets (high→low):
      1. new since last run (`new_identities`, e.g. P4 incremental cursor)
      2. source authority (official registry)
      3. claimed-write keyword signal — a boost, not a gate
    with two *reserved* slices carved off the cap so they can't be starved:
      - exploration (~20%): never-probed, none-tier servers — samples outside the
        keyword prior to prove (and correct) its leakiness
      - re-verification (~15%): headline tools past `DISCOVERY_DECAY_DAYS`
    Rotation: never-probed first, then oldest `last_discovered`, then identity.
    Reserves use `int(cap * frac)`, so caps below ~5 (exploration) / ~7 (reverify)
    floor the respective guarantee to 0 — fine at the production cap (150), but a
    cost lever set very low disables them.
    """
    new_ids: Set[str] = set(new_identities or ())
    if cap <= 0:
        return []

    eligible = []
    for rec in records:
        if not rec.remote_url:
            continue
        seen = last_discovered.get(rec.identity)
        if seen and days_between(seen, run_date) < cadence_days:
            continue  # discovered recently; let it rotate later
        eligible.append(rec)

    def priority_key(rec: RegistryServerRecord):
        new = 0 if rec.identity in new_ids else 1
        authority = 0 if _has_authority(rec) else 1
        claimed = 0 if is_claimed_write(rec) else 1
        never = 0 if rec.identity not in last_discovered else 1
        last = last_discovered.get(rec.identity, "")
        return (new, authority, claimed, never, last, rec.identity)

    reverify = sorted(
        (r for r in eligible if _needs_reverify(r, run_date)),
        key=lambda r: (last_discovered.get(r.identity, ""), r.identity),
    )
    explore = sorted(
        (r for r in eligible
         if r.identity not in last_discovered and evidence_tier(r.evidence) == "none"),
        key=lambda r: r.identity,
    )
    main = sorted(eligible, key=priority_key)

    chosen: List[RegistryServerRecord] = []
    chosen_ids: Set[str] = set()

    def fill(pool: Iterable[RegistryServerRecord], limit: int) -> None:
        for rec in pool:
            if len(chosen) >= cap or limit <= 0:
                break
            if rec.identity in chosen_ids:
                continue
            chosen.append(rec)
            chosen_ids.add(rec.identity)
            limit -= 1

    fill(reverify, int(cap * REVERIFY_FRACTION))
    fill(explore, int(cap * EXPLORATION_FRACTION))
    fill(main, cap)  # priority fill; reclaims any unused reserve up to cap
    return chosen


def run_discovery(
    candidates: List[RegistryServerRecord],
    run_date: str,
    workers: int = 8,
    timeout: int = 15,
) -> Dict[str, str]:
    """Probe candidates concurrently. Workers only fetch/parse. Returns
    {identity: discovered_date} for those probed; mutates each record's
    confidence_by_source['tools'] on the MAIN thread after the pool joins.
    """
    from .classifier import RANK, classify_tool, max_confidence

    def probe(rec: RegistryServerRecord) -> Tuple[str, list, dict]:
        tools, result = discover_remote_tools("registry", rec.identity, "registry", rec.remote_url, timeout=timeout)
        return rec.identity, tools, result

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, rec) for rec in candidates]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:  # one bad endpoint must not kill the batch
                continue

    def _ground(rec: RegistryServerRecord, tools: list, run_date: str) -> None:
        """Classify tools and ground results onto rec (main-thread mutation)."""
        for tool in tools:
            tool.write_confidence, tool.evidence = classify_tool(tool)
        confs = [t.write_confidence for t in tools]
        rec.confidence_by_source["tools"] = {"confidence": max_confidence(confs), "date": run_date}
        # Persist the top-N WRITE tools (most-confident first, then by name for a
        # deterministic tie-break) so P2/P3 have per-tool action class + prompts
        # without re-probing — bounded so the record stays small.
        write_tools = [t for t in tools if t.write_confidence in ("medium", "high")]
        write_tools.sort(key=lambda t: (-RANK.get(t.write_confidence, 0), t.name))
        rec.tools = write_tools[:TOP_N_WRITE_TOOLS]
        # Propagate observed write evidence from the live probe (deduped by
        # kind/value/confidence): mcp_annotation hints AND tool_text write verbs —
        # the latter is what lifts a probed record to the `verified_tools` tier.
        existing_keys = {
            (item.get("kind"), item.get("value"), item.get("confidence"))
            for item in rec.evidence
        }
        for tool in tools:
            for ev in tool.evidence:
                if ev.get("kind") in ("mcp_annotation", "tool_text"):
                    key = (ev.get("kind"), ev.get("value"), ev.get("confidence"))
                    if key not in existing_keys:
                        rec.evidence.append(ev)
                        existing_keys.add(key)

    by_id = {rec.identity: rec for rec in candidates}
    discovered: Dict[str, str] = {}
    for identity, tools, result in results:
        rec = by_id.get(identity)
        if rec is None:
            continue
        discovered[identity] = run_date
        if result.get("ok") and tools:
            _ground(rec, tools, run_date)
    return discovered
