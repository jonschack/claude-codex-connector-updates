from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

# Grok research layer (operator-run, driven via Claude-in-Chrome over grok.com).
# Grok's live-X access surfaces what's VIRAL; this module turns its self-formatted
# answers into structured candidates and verifies them ("candidates -> verify
# first") before anything reaches meetup content. Parse + verify are pure and
# unit-tested; the browser drive lives in the /grok-research skill.

SourceChecker = Callable[[str], bool]

# trailing tokens stripped when matching a finding name against a known catalog
_NAME_SUFFIXES = (" mcp server", " mcp", " server", " connector", " app")


@dataclass
class GrokFinding:
    name: str
    capability: str = ""
    why_viral: str = ""
    source_url: str = ""
    example_prompt: str = ""
    query: str = ""
    verdict: str = "claimed"  # "verified" | "claimed" | "rejected"
    verify_note: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "capability": self.capability,
            "why_viral": self.why_viral,
            "source_url": self.source_url,
            "example_prompt": self.example_prompt,
            "query": self.query,
            "verdict": self.verdict,
            "verify_note": self.verify_note,
        }


def _name_variants(name: str) -> Set[str]:
    n = " ".join(name.lower().split())
    variants = {n}
    for suffix in _NAME_SUFFIXES:
        if n.endswith(suffix):
            variants.add(n[: -len(suffix)].strip())
    return {v for v in variants if v}


def parse_grok_findings(text: str, query: str = "") -> List[GrokFinding]:
    """Parse Grok's pipe-delimited rows (plain or markdown-table) into findings.
    Columns: name | capability | why_viral | source_url | example_prompt.
    Header, separator, and prose lines are skipped."""
    findings: List[GrokFinding] = []
    for line in (text or "").splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        while cells and cells[0] == "":
            cells.pop(0)
        while cells and cells[-1] == "":
            cells.pop()
        if not cells:
            continue
        name = cells[0]
        if not name or name.lower() == "name":
            continue
        if set(name) <= set("-: "):  # markdown separator row (---, :---:)
            continue

        def cell(i: int) -> str:
            return cells[i] if i < len(cells) else ""

        findings.append(GrokFinding(
            name=name,
            capability=cell(1),
            why_viral=cell(2),
            source_url=cell(3),
            example_prompt=cell(4),
            query=query,
        ))
    return findings


def verify_candidates(
    findings: List[GrokFinding],
    source_checker: SourceChecker,
    known_names: Optional[Set[str]] = None,
) -> List[GrokFinding]:
    """Tag each finding verified/claimed/rejected. A name matching the known
    connector catalog, or a source URL that resolves, → verified. A source that
    doesn't resolve → claimed (kept, labeled). No source → rejected.
    `source_checker` is injectable; failures degrade to claimed, never crash."""
    known: Set[str] = set()
    for kn in (known_names or set()):
        known |= _name_variants(kn)

    for finding in findings:
        if _name_variants(finding.name) & known:
            finding.verdict = "verified"
            finding.verify_note = "matches known connector catalog"
            continue
        if finding.source_url:
            resolved = False
            try:
                resolved = bool(source_checker(finding.source_url))
            except Exception as exc:  # network/parse failure must not crash a run
                finding.verify_note = f"source check failed: {type(exc).__name__}"
                resolved = False
            if resolved:
                finding.verdict = "verified"
                finding.verify_note = "source URL resolves"
            else:
                finding.verdict = "claimed"
                finding.verify_note = finding.verify_note or "source unverified"
        else:
            finding.verdict = "rejected"
            finding.verify_note = "no source"
    return findings


# --- thin live helpers for the /grok-research skill (not unit-tested) ---

def known_connector_names(awesome_readme: str) -> Set[str]:
    """Extract connector display names from an awesome-list README
    (`- [Name](url) - ...`), as the local verification corpus."""
    names: Set[str] = set()
    for match in re.finditer(r"^\s*[-*]\s*\[([^\]]+)\]\(", awesome_readme or "", flags=re.M):
        names.add(match.group(1).strip())
    return names


def default_source_checker(url: str) -> bool:
    """Resolve a candidate's cited URL via the shared fetch path (200 + body)."""
    from .utils import fetch_text

    if not url or not url.lower().startswith(("http://", "https://")):
        return False
    text, meta = fetch_text(url)
    status = meta.get("status")
    return bool(text) and (status is None or 200 <= int(status) < 400)


def to_signal_records(findings: List[GrokFinding]):
    """Verified/claimed findings → SignalRecords for the signals/highlights feed
    (rejected are dropped). source is `grok:<verdict>` so provenance is visible."""
    from .signals import SignalRecord

    out = []
    for f in findings:
        if f.verdict == "rejected":
            continue
        summary = f.capability
        if f.why_viral:
            summary = f"{summary} — viral: {f.why_viral}" if summary else f.why_viral
        out.append(SignalRecord(
            source=f"grok:{f.verdict}",
            title=f.name,
            url=f.source_url,
            published="",
            summary=summary,
        ))
    return out
