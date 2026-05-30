from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from .mcp_discovery import discover_remote_tools
from .registries.base import RegistryServerRecord


def _days_between(a: str, b: str) -> int:
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    except ValueError:
        return 10 ** 6


def select_discovery_candidates(
    records: List[RegistryServerRecord],
    cap: int,
    last_discovered: Dict[str, str],
    cadence_days: int,
    run_date: str,
) -> List[RegistryServerRecord]:
    """Deterministic, capped, rotating selection of remote servers to probe."""
    eligible = []
    for rec in records:
        if not rec.remote_url:
            continue
        seen = last_discovered.get(rec.identity)
        if seen and _days_between(seen, run_date) < cadence_days:
            continue  # discovered recently; let it rotate later
        eligible.append(rec)

    def sort_key(rec: RegistryServerRecord):
        never = 0 if rec.identity not in last_discovered else 1
        last = last_discovered.get(rec.identity, "")
        return (never, last, rec.identity)

    eligible.sort(key=sort_key)
    return eligible[:cap]


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
    from .classifier import classify_tool, max_confidence

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

    by_id = {rec.identity: rec for rec in candidates}
    discovered: Dict[str, str] = {}
    for identity, tools, result in results:
        rec = by_id.get(identity)
        if rec is None:
            continue
        discovered[identity] = run_date
        if result.get("ok") and tools:
            confs = []
            for tool in tools:
                tool.write_confidence, tool.evidence = classify_tool(tool)
                confs.append(tool.write_confidence)
            rec.confidence_by_source["tools"] = {"confidence": max_confidence(confs), "date": run_date}
    return discovered
