from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .action_class import record_action_classes
from .action_power import power_tier_for, record_power
from .classifier import EVIDENCE_TIER_RANK, evidence_tier, evidence_tiers
from .frontier import freshness, score
from .grok_research import load_radar_state
from .registries.base import RegistryServerRecord
from .registry_discovery import days_between
from .utils import write_json, write_text

# Phase 2: push the write frontier. Every daily run renders an always-current
# ranked board (WRITE_FRONTIER_NOW.md + write_frontier_current.json); a weekly
# idempotent digest narrates the delta; same-day alerts fire on standout new
# high-power write tools. Ranking here is the P2-lite key (evidence_tier ->
# power_tier -> recency); P3 swaps in the full score. Engagement is the rank only
# WITHIN the viral section — it never lifts a claimed item into the headline.

# Evidence tiers strong enough to headline (we've observed the actual behavior).
HEADLINE_TIERS = {"verified_tools", "annotation", "declared_manifest"}
DIGEST_WINDOW_DAYS = 7


@dataclass
class FrontierEntry:
    identity: str
    name: str
    section: str                       # "headline" | "emerging" | "viral"
    evidence_tier: str = "none"
    power_tier: str = "low"
    recency: str = ""                  # iso date (source-reported), "" if unknown
    action_classes: List[str] = field(default_factory=list)
    example_prompt: str = ""
    source_url: str = ""
    engagement: int = 0                # viral only
    why: str = ""
    confidence: str = "low"            # power-classification confidence (P3)
    corroboration: int = 1            # distinct evidence tiers attesting (P3)
    frontier_score: float = 0.0        # P3 lexicographic score (headline/emerging)

    def to_dict(self) -> dict:
        return {
            "identity": self.identity, "name": self.name, "section": self.section,
            "evidence_tier": self.evidence_tier, "power_tier": self.power_tier,
            "recency": self.recency, "action_classes": self.action_classes,
            "example_prompt": self.example_prompt, "source_url": self.source_url,
            "engagement": self.engagement, "why": self.why,
            "confidence": self.confidence, "corroboration": self.corroboration,
            "frontier_score": round(self.frontier_score, 4),
        }


def _recency(rec: RegistryServerRecord) -> str:
    return max((s.get("last_updated", "") for s in rec.sources), default="")


def _example_prompt(rec: RegistryServerRecord) -> str:
    """Honest, tool-derived example prompt (never invented capability)."""
    for tool in rec.tools:
        if tool.example_prompt:
            return tool.example_prompt
    if rec.tools:
        return f'Claude, have {rec.name} {rec.tools[0].name.replace("_", " ")}'
    classes = [c for c in record_action_classes(rec) if c != "other"]
    if classes:
        return f'Claude, use {rec.name} for {classes[0].replace("_", " ")}'
    return f'Claude, use {rec.name}'


def build_frontier(records: Dict[str, RegistryServerRecord],
                   grok_state: Dict[str, dict], run_date: str = "") -> List[FrontierEntry]:
    """Build frontier entries from registry records (headline/emerging by evidence
    tier, scored by the P3 lexicographic frontier score) and the Grok radar
    (viral, ranked separately on engagement)."""
    entries: List[FrontierEntry] = []
    for rec in records.values():
        tier = evidence_tier(rec.evidence)
        if tier == "none" and rec.write_confidence not in ("medium", "high"):
            continue  # no write signal at all
        section = "headline" if tier in HEADLINE_TIERS else "emerging"
        power_tier, confidence = record_power(rec)
        recency = _recency(rec)
        corroboration = max(1, len(evidence_tiers(rec.evidence)))
        entries.append(FrontierEntry(
            identity=rec.identity, name=rec.name, section=section,
            evidence_tier=tier, power_tier=power_tier, recency=recency,
            action_classes=record_action_classes(rec),
            example_prompt=_example_prompt(rec),
            source_url=rec.repo_url or rec.remote_url,
            confidence=confidence, corroboration=corroboration,
            frontier_score=score(tier, power_tier, freshness(recency, run_date),
                                  confidence, corroboration=corroboration),
        ))
    for key, g in grok_state.items():
        entries.append(FrontierEntry(
            identity="grok:" + key, name=g.get("name", ""), section="viral",
            # power_tier is informational in the JSON only; viral ranks on
            # engagement and never participates in the headline score.
            power_tier=power_tier_for(f"{g.get('name', '')} {g.get('capability', '')}"),
            action_classes=[], example_prompt=g.get("example_prompt", ""),
            source_url=g.get("source_url", ""),
            engagement=int(g.get("peak_engagement", 0) or 0), why=g.get("why_viral", ""),
        ))
    return entries


def ranked_section(entries: List[FrontierEntry], section: str) -> List[FrontierEntry]:
    """Entries in one section, ranked. Viral ranks by engagement; headline/emerging
    by the P3 frontier_score, name-stable for determinism."""
    items = [e for e in entries if e.section == section]
    if section == "viral":
        return sorted(items, key=lambda e: (-e.engagement, e.name.lower(), e.identity))
    items.sort(key=lambda e: (e.name.lower(), e.identity))
    items.sort(key=lambda e: e.frontier_score, reverse=True)
    return items


def radar_age_days(grok_state: Dict[str, dict], run_date: str) -> Optional[int]:
    """Age (days) of the freshest radar sighting, or None if the radar is empty."""
    last = max((g.get("last_seen", "") for g in grok_state.values()), default="")
    return days_between(last, run_date) if last else None


def _staleness_line(age: Optional[int], window: int = DIGEST_WINDOW_DAYS) -> str:
    if age is None:
        return "⚠️ Grok radar empty — viral coverage missing; run `/grok-research`."
    if age > window:
        return (f"⚠️ Grok radar stale ({age} days) — viral coverage incomplete; "
                f"run `/grok-research` before the weekly digest.")
    return f"Grok radar fresh ({age} days old)."


def _table(entries: List[FrontierEntry], cap: int) -> List[str]:
    rows = ["| # | Server | Evidence | Power | Recency | Try it |",
            "| --- | --- | --- | --- | --- | --- |"]
    for i, e in enumerate(entries[:cap], 1):
        prompt = e.example_prompt.replace("|", "\\|")
        recency = (e.recency or "—")[:10]  # show the date, not a full ISO timestamp
        rows.append(f"| {i} | {e.name} | {e.evidence_tier} | {e.power_tier} | "
                    f"{recency} | {prompt} |")
    if len(entries) > cap:
        rows.append(f"- … {len(entries) - cap} more; see `write_frontier_current.json`.")
    return rows


def render_board(entries: List[FrontierEntry], run_date: str,
                 grok_state: Dict[str, dict], cap: int = 25) -> str:
    """The always-current WRITE_FRONTIER_NOW.md board."""
    headline = ranked_section(entries, "headline")
    emerging = ranked_section(entries, "emerging")
    viral = ranked_section(entries, "viral")
    lines = [
        f"# Write Frontier — {run_date}",
        "",
        "Cutting-edge **write-capable** MCP tools (the ones that can DO things), "
        "ranked by evidence strength, then action power, then recency.",
        "",
        f"## ✅ Verified / Declared — Headline ({len(headline)})",
        "",
    ]
    lines += _table(headline, cap) if headline else ["_None yet._"]
    lines += ["", f"## 🌱 Emerging — Claimed ({len(emerging)})", ""]
    lines += _table(emerging, cap) if emerging else ["_None yet._"]
    lines += ["", f"## 🔥 Viral (Grok) ({len(viral)})", "",
              _staleness_line(radar_age_days(grok_state, run_date)), ""]
    if viral:
        lines += ["| # | Server | Engagement | Why | Try it |",
                  "| --- | --- | --- | --- | --- |"]
        for i, e in enumerate(viral[:cap], 1):
            why = e.why.replace("|", "\\|")
            prompt = e.example_prompt.replace("|", "\\|")
            lines.append(f"| {i} | {e.name} | {e.engagement} | {why} | {prompt} |")
    else:
        lines.append("_No radar data._")
    return "\n".join(lines) + "\n"


def board_json(entries: List[FrontierEntry], run_date: str) -> dict:
    return {
        "run_date": run_date,
        "entries": [e.to_dict() for e in (
            ranked_section(entries, "headline")
            + ranked_section(entries, "emerging")
            + ranked_section(entries, "viral"))],
    }


# --- weekly delta + alerts + teaching artifact ---------------------------------

def weekly_delta(current: List[dict], prior: List[dict]) -> dict:
    """new / newly-verified / risen, comparing two board_json `entries` lists."""
    prior_by_id = {d["identity"]: d for d in prior}
    new, newly_verified, risen = [], [], []
    for d in current:
        pid = d["identity"]
        prev = prior_by_id.get(pid)
        if prev is None:
            new.append(d)
            continue
        cur_rank = EVIDENCE_TIER_RANK.get(d.get("evidence_tier", "none"), 0)
        prev_rank = EVIDENCE_TIER_RANK.get(prev.get("evidence_tier", "none"), 0)
        if cur_rank > prev_rank and d.get("evidence_tier") in HEADLINE_TIERS:
            newly_verified.append(d)
        if d.get("section") == "viral" and int(d.get("engagement", 0) or 0) > int(prev.get("engagement", 0) or 0):
            risen.append(d)
    return {"new": new, "newly_verified": newly_verified, "risen": risen}


def is_headline_high(entry) -> bool:
    """Headline-tier (verified/declared) AND high action power — the alert bar."""
    tier = entry["evidence_tier"] if isinstance(entry, dict) else entry.evidence_tier
    section = entry["section"] if isinstance(entry, dict) else entry.section
    power = entry["power_tier"] if isinstance(entry, dict) else entry.power_tier
    return section == "headline" and power == "high"


# frontier_capability fires at/above this score (declared+ tier with some power);
# tunable via MCP_NEWSLETTER_FRONTIER_ALERT_THRESHOLD.
FRONTIER_SCORE_THRESHOLD = 2000.0


def frontier_events(current: List[dict], prior: List[dict],
                    threshold: float = FRONTIER_SCORE_THRESHOLD,
                    cap: int = 50) -> List[dict]:
    """Derive frontier events by diffing the current board against the prior:
      - `write_verified` (with `first_seen` flag): a server that entered a headline
        evidence tier this run (merges the old new_write_tool + write_verified).
      - `frontier_capability`: a server whose frontier_score crossed `threshold`
        upward this run.
    Flood-capped at `cap` (highest-score first)."""
    prior_by_id = {d.get("identity"): d for d in prior}
    events: List[dict] = []
    for d in current:
        if d.get("section") == "viral":
            continue
        prev = prior_by_id.get(d.get("identity"))
        cur_head = d.get("evidence_tier") in HEADLINE_TIERS
        prev_head = bool(prev) and prev.get("evidence_tier") in HEADLINE_TIERS
        if cur_head and not prev_head:
            events.append({"event_type": "write_verified", "identity": d.get("identity"),
                           "name": d.get("name"), "first_seen": prev is None,
                           "evidence_tier": d.get("evidence_tier"),
                           "power_tier": d.get("power_tier"),
                           "frontier_score": d.get("frontier_score", 0)})
        cur_score = float(d.get("frontier_score", 0) or 0)
        prev_score = float(prev.get("frontier_score", 0) or 0) if prev else 0.0
        if cur_score >= threshold and prev_score < threshold:
            events.append({"event_type": "frontier_capability", "identity": d.get("identity"),
                           "name": d.get("name"), "frontier_score": cur_score})
    events.sort(key=lambda e: e.get("frontier_score", 0), reverse=True)
    return events[:cap]


def select_alerts(entries: List[FrontierEntry],
                  prior_headline_high: Set[str]) -> List[FrontierEntry]:
    """Same-day alert bar (b): any tool that is high-power verified/declared NOW
    and was NOT already in that set — so a brand-new tool AND a tool freshly
    promoted from emerging→headline (newly verified) both fire, regardless of
    vendor fame or virality. `prior_headline_high` = the identities that were
    headline+high on the prior run's board."""
    return [e for e in entries
            if is_headline_high(e) and e.identity not in prior_headline_high]


def render_digest(delta: dict, run_date: str) -> str:
    def block(title, items):
        out = [f"### {title} ({len(items)})", ""]
        if not items:
            out.append("_None._")
        for d in items:
            tail = f" — {d.get('why')}" if d.get("why") else ""
            out.append(f"- **{d.get('name')}** ({d.get('evidence_tier')}, "
                       f"{d.get('power_tier')} power){tail}")
        out.append("")
        return out

    lines = [f"# Write Frontier — Weekly Digest ({run_date})", ""]
    lines += block("🆕 New on the frontier", delta.get("new", []))
    lines += block("✅ Newly verified", delta.get("newly_verified", []))
    lines += block("📈 Rising (viral)", delta.get("risen", []))
    return "\n".join(lines) + "\n"


def render_teaching_artifact(entries: List[FrontierEntry], run_date: str) -> str:
    """Prompt-first, action-class-grouped lead magnet: "What You Can Now Ask Your
    AI To Do — Write Edition". Headline + emerging only (things that actually act)."""
    by_class: Dict[str, List[FrontierEntry]] = {}
    for e in entries:
        if e.section == "viral":
            continue
        for cls in (e.action_classes or ["other"]):
            by_class.setdefault(cls, []).append(e)
    lines = [
        "# What You Can Now Ask Your AI To Do — Write Edition",
        "",
        f"_Fresh as of {run_date}. Each line is a real prompt backed by a tool that "
        "can actually perform the action._",
        "",
    ]
    for cls in sorted(by_class, key=lambda c: (-len(by_class[c]), c)):
        if cls == "other":
            continue
        lines.append(f"## {cls.replace('_', ' ').title()}")
        # rank the (mixed headline+emerging) entries by the P3 frontier score
        ranked = sorted(by_class[cls], key=lambda e: (e.name.lower(), e.identity))
        ranked.sort(key=lambda e: e.frontier_score, reverse=True)
        seen = set()
        for e in ranked:
            if e.example_prompt in seen:
                continue
            seen.add(e.example_prompt)
            lines.append(f"- {e.example_prompt}  _( {e.name}, {e.evidence_tier} )_")
        lines.append("")
    return "\n".join(lines) + "\n"


# --- orchestrator (daily run: board + alerts + idempotent weekly digest) -------

def run_frontier_report(root: Path, run_date: str,
                        records: Dict[str, RegistryServerRecord], meta) -> dict:
    """Render the daily board + JSON, select same-day alerts (diffed against the
    PRIOR run's board), emit the weekly digest when due (idempotent on
    meta.last_frontier_digest), and draft the meetup teaching artifact. Does NOT
    send email — returns the alert entries + digest body for the caller to send.
    Mutates meta.last_frontier_digest when the digest fires.
    """
    cur = root / "data" / "current"
    grok_state = load_radar_state(cur / "grok_radar_state.jsonl")
    entries = build_frontier(records, grok_state, run_date)

    # alerts diff against the headline+high set on the PRIOR run's board (read it
    # BEFORE overwriting), so a brand-new OR newly-promoted high-power tool fires.
    current_path = cur / "write_frontier_current.json"
    prior_entries = _read_entries(current_path)
    prior_headline_high = {e.get("identity") for e in prior_entries if is_headline_high(e)}
    alerts = select_alerts(entries, prior_headline_high)

    # write the always-current board + json (board reflects THIS run)
    write_text(cur / "WRITE_FRONTIER_NOW.md", render_board(entries, run_date, grok_state))
    new_board = board_json(entries, run_date)
    write_json(current_path, new_board)

    # frontier events (write_verified / frontier_capability) vs the prior board
    threshold = float(os.environ.get("MCP_NEWSLETTER_FRONTIER_ALERT_THRESHOLD",
                                     str(FRONTIER_SCORE_THRESHOLD)))
    events = frontier_events(new_board["entries"], prior_entries, threshold)
    write_json(cur / "write_frontier_events.json", {"run_date": run_date, "events": events})

    digest_due, digest_body = _weekly_digest_step(cur, run_date, new_board, meta)

    # meetup teaching artifact draft (human-approved; never auto-published)
    teaching_dir = root / "meetup-hormozi" / "assets"
    if teaching_dir.exists():
        write_text(teaching_dir / "08-write-frontier-teaching.md",
                   render_teaching_artifact(entries, run_date))

    return {
        "alerts": alerts,
        "digest_due": digest_due,
        "digest_body": digest_body,
        "radar_age_days": radar_age_days(grok_state, run_date),
        "entry_count": len(entries),
        "events": events,
    }


def _read_entries(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    except (json.JSONDecodeError, OSError):
        return []


def _weekly_digest_step(cur: Path, run_date: str, new_board: dict, meta):
    """Emit the weekly digest iff due (idempotent on meta.last_frontier_digest).
    Stamps meta and snapshots the baseline so next week's delta is correct."""
    due = (not meta.last_frontier_digest
           or days_between(meta.last_frontier_digest, run_date) >= DIGEST_WINDOW_DAYS)
    if not due:
        return False, ""
    baseline = _read_entries(cur / "write_frontier_last_digest.json")
    body = render_digest(weekly_delta(new_board["entries"], baseline), run_date)
    write_text(cur / "WRITE_FRONTIER.md", body)
    write_json(cur / "write_frontier_last_digest.json", new_board)
    meta.last_frontier_digest = run_date
    return True, body
