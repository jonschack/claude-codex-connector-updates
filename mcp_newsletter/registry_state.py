from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .classifier import reportable
from .registries.base import RegistryServerRecord
from .utils import ensure_dir


def load_state(path: Path) -> Dict[str, RegistryServerRecord]:
    if not path.exists():
        return {}
    out: Dict[str, RegistryServerRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = RegistryServerRecord.from_jsonl(line)
        out[rec.identity] = rec
    return out


def write_state(path: Path, records: List[RegistryServerRecord]) -> None:
    ensure_dir(path.parent)
    lines = [rec.to_jsonl() for rec in sorted(records, key=lambda r: r.identity)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


@dataclass
class RegistryMeta:
    seeded_sources: Dict[str, str] = field(default_factory=dict)   # source -> first seeded date
    liveness: Dict[str, int] = field(default_factory=dict)         # identity -> consecutive misses
    last_discovered: Dict[str, str] = field(default_factory=dict)  # identity -> date
    last_manifest_parsed: Dict[str, str] = field(default_factory=dict)  # identity -> date
    last_frontier_digest: str = ""  # date the weekly frontier digest last emitted
    first_seen: Dict[str, str] = field(default_factory=dict)  # identity -> date first catalogued
    official_cursor: str = ""  # P4: updated_since high-watermark for incremental pulls
    github_stars: Dict[str, int] = field(default_factory=dict)  # P4: candidate star snapshot

    @classmethod
    def load(cls, path: Path) -> "RegistryMeta":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            seeded_sources=data.get("seeded_sources", {}),
            liveness=data.get("liveness", {}),
            last_discovered=data.get("last_discovered", {}),
            last_manifest_parsed=data.get("last_manifest_parsed", {}),
            last_frontier_digest=data.get("last_frontier_digest", ""),
            first_seen=data.get("first_seen", {}),
            official_cursor=data.get("official_cursor", ""),
            github_stars=data.get("github_stars", {}),
        )

    def dump(self, path: Path) -> None:
        ensure_dir(path.parent)
        path.write_text(json.dumps({
            "seeded_sources": self.seeded_sources,
            "liveness": self.liveness,
            "last_discovered": self.last_discovered,
            "last_manifest_parsed": self.last_manifest_parsed,
            "last_frontier_digest": self.last_frontier_digest,
            "first_seen": self.first_seen,
            "official_cursor": self.official_cursor,
            "github_stars": self.github_stars,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _event(run_date, event_type, rec, summary):
    return {
        "run_date": run_date,
        "event_type": event_type,
        "identity": rec.identity,
        "confidence": rec.write_confidence,
        "summary": summary,
        "evidence": rec.evidence,
        "sources": sorted({s.get("source", "") for s in rec.sources}),
    }


def _carrying_sources(rec: RegistryServerRecord) -> List[str]:
    return sorted({s.get("source", "") for s in rec.sources})


def diff_and_events(
    prior: Dict[str, RegistryServerRecord],
    current: Dict[str, RegistryServerRecord],
    run_date: str,
    source_ok: Dict[str, bool],
    meta: RegistryMeta,
    delist_runs: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, RegistryServerRecord], RegistryMeta]:
    events: List[Dict[str, Any]] = []

    # Which sources had a successful run THIS time (determines seeding + liveness).
    successful_sources = {s for s, ok in source_ok.items() if ok}
    first_seed = {s for s in successful_sources if s not in meta.seeded_sources}
    for s in first_seed:
        meta.seeded_sources[s] = run_date

    def source_is_seeded(rec) -> bool:
        # A record is "past baseline" if any of its carrying sources was seeded
        # on an earlier run (not just this one).
        for s in _carrying_sources(rec):
            seeded_on = meta.seeded_sources.get(s)
            if seeded_on and seeded_on < run_date:
                return True
        return False

    # --- additions / changes / regressions ---
    for identity in sorted(current):
        rec = current[identity]
        prev = prior.get(identity)
        if prev is None:
            if reportable(rec.write_confidence) and source_is_seeded(rec):
                events.append(_event(run_date, "new_write_server", rec,
                                     f"New write-capable server: {rec.name}"))
            continue
        # status change up
        if not reportable(prev.write_confidence) and reportable(rec.write_confidence):
            events.append(_event(run_date, "write_status_changed", rec,
                                 f"Server became write-capable: {rec.name}"))
            continue
        # regression — only when a SHARED evidence source dropped
        if reportable(prev.write_confidence) and not reportable(rec.write_confidence):
            if _regressed_like_for_like(prev, rec):
                events.append(_event(run_date, "write_status_regressed", rec,
                                     f"Server lost write capability: {rec.name}"))
        # new_source — an existing write-capable server now appears in a registry
        # it was not seen in before (low-noise; reported as a count, not a row)
        if reportable(rec.write_confidence):
            prev_sources = {s.get("source") for s in prev.sources}
            cur_sources = {s.get("source") for s in rec.sources}
            added = sorted(
                s for s in (cur_sources - prev_sources)
                if meta.seeded_sources.get(s, run_date) < run_date
            )
            if added:
                events.append(_event(run_date, "new_source", rec,
                                     f"{rec.name} newly listed in: {', '.join(added)}"))

    # --- liveness / delisting ---
    new_state = dict(current)
    for identity in sorted(prior):
        if identity in current:
            meta.liveness.pop(identity, None)
            continue
        prev = prior[identity]
        # Only count a miss if at least one of its carrying sources succeeded.
        if not (set(_carrying_sources(prev)) & successful_sources):
            new_state[identity] = prev   # source down: keep, freeze liveness
            continue
        misses = meta.liveness.get(identity, 0) + 1
        if misses >= delist_runs:
            if reportable(prev.write_confidence):
                events.append(_event(run_date, "delisted", prev,
                                     f"Write-capable server delisted: {prev.name}"))
            meta.liveness.pop(identity, None)
            meta.last_discovered.pop(identity, None)
            meta.last_manifest_parsed.pop(identity, None)
            meta.first_seen.pop(identity, None)
            # dropped from new_state (truly gone)
        else:
            meta.liveness[identity] = misses
            new_state[identity] = prev

    events.sort(key=lambda e: (e["event_type"], e["identity"]))
    return events, new_state, meta


def _regressed_like_for_like(prev: RegistryServerRecord, cur: RegistryServerRecord) -> bool:
    """True only if a source present in BOTH dropped from reportable to not."""
    for source, prev_info in prev.confidence_by_source.items():
        cur_info = cur.confidence_by_source.get(source)
        if not cur_info:
            continue  # source absent this run -> not comparable -> no regression
        if reportable(prev_info["confidence"]) and not reportable(cur_info["confidence"]):
            return True
    return False
