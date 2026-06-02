from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

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


# --- radar: query matrix, engagement, dedup state (the "every post" extension) ---

# High-signal accounts whose timelines reliably carry viral MCP demos/launches.
SEED_ACCOUNTS: List[str] = [
    "AnthropicAI", "modelcontextprotocol", "ahujasid", "alexalbert__",
    "_philschmid", "OpenAIDevs", "skirano",
]

# Term variants swept each run; combined with an engagement floor + time window
# into a query matrix so recall doesn't depend on Grok picking good searches.
_TERMS: List[str] = [
    '("MCP" OR "model context protocol")',
    '"MCP server"',
    '"Claude connector"',
    '"MCP connector"',
    'MCP (Claude OR Cursor OR "Claude Code" OR Codex)',
]


def build_query_matrix(min_faves: int = 10, since: str = "") -> List[str]:
    """Exhaustive X-search matrix: {term variants + seed accounts} × engagement
    floor × time window. Grok is told to run each search verbatim, so coverage
    doesn't hinge on its own query choices."""
    flt = f"min_faves:{min_faves}"
    win = f" since:{since}" if since else ""
    queries = [f"{term} {flt}{win}" for term in _TERMS]
    for account in SEED_ACCOUNTS:
        queries.append(f'from:{account} (MCP OR connector OR "model context protocol"){win}')
    return queries


_ENGAGEMENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kK])?\s*\+?\s*(?:likes?|reposts?|views?)")


def extract_engagement(text: str) -> int:
    """Best engagement count from a why_viral blurb (e.g. '1.8k+ likes' -> 1800).
    Only counts numbers attached to likes/reposts/views, so '17k tickers' is
    ignored."""
    best = 0
    for num, k in _ENGAGEMENT_RE.findall(text or ""):
        value = float(num) * (1000 if k else 1)
        best = max(best, int(value))
    return best


def finding_key(finding: GrokFinding) -> str:
    """Stable dedup key: normalized source URL, else slugified name."""
    url = (finding.source_url or "").strip().lower()
    if url:
        return re.sub(r"^https?://", "", url).rstrip("/")
    from .utils import slugify
    return "name:" + slugify(finding.name)


def merge_into_state(
    state: Dict[str, dict],
    findings: List[GrokFinding],
    run_date: str,
) -> Tuple[Dict[str, dict], List[GrokFinding], List[GrokFinding]]:
    """Merge a sweep's findings into persistent radar state. Returns
    (state, new, rising): `new` = first-ever sightings; `rising` = already-seen
    posts whose engagement crossed its prior peak (slow-burners going viral).
    first_seen is preserved; peak_engagement is high-water-marked."""
    new: List[GrokFinding] = []
    rising: List[GrokFinding] = []
    for finding in findings:
        key = finding_key(finding)
        engagement = extract_engagement(finding.why_viral)
        if key not in state:
            record = finding.to_dict()
            record.update({"key": key, "first_seen": run_date, "last_seen": run_date,
                           "peak_engagement": engagement})
            state[key] = record
            new.append(finding)
        else:
            record = state[key]
            record["last_seen"] = run_date
            if engagement > int(record.get("peak_engagement", 0)):
                record["peak_engagement"] = engagement
                rising.append(finding)
    return state, new, rising


def load_radar_state(path) -> Dict[str, dict]:
    p = Path(path)
    state: Dict[str, dict] = {}
    if not p.exists():
        return state
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = record.get("key") or record.get("source_url") or record.get("name")
        if key:
            state[key] = record
    return state


def write_radar_state(path, state: Dict[str, dict]) -> None:
    rows = sorted(state.values(), key=lambda r: (-int(r.get("peak_engagement", 0)), str(r.get("key"))))
    Path(path).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


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
