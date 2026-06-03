from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from .classifier import WRITE_RE, evidence_tier
from .identity import github_owner_repo
from .models import ToolRecord
from .registries.base import RegistryServerRecord
from .registry_discovery import (
    EXPLORATION_FRACTION,
    TOP_N_WRITE_TOOLS,
    days_between,
    is_claimed_write,
)

# Static `declared_manifest` tier: for stdio servers (the ~91% with no remote_url
# we can't probe live), parse the repo's PUBLISHED tool declarations — server.json
# tool arrays and README "Tools" sections — with NO execution. Evidence ranks
# between claimed_description and annotation (see classifier.EVIDENCE_TIER_RANK).
# Bounded to a cap/cadence-rotated candidate set, never all ~30k repos.

# A tool name looks like an identifier: starts with a letter, ≥3 chars.
_TOOL_NAME = r"[A-Za-z][A-Za-z0-9_]{2,}"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# A "Tools" heading must be a recognized tool-listing title — not any heading that
# merely contains the word (e.g. "Troubleshooting Tools", "Recommended Tools").
_TOOLS_HEADINGS = {
    "tools", "available tools", "supported tools", "mcp tools", "the tools",
    "tool reference", "provided tools", "exposed tools", "tools provided",
}


def _is_tools_heading(text: str) -> bool:
    norm = re.sub(r"[^a-z ]+", "", text.lower()).strip()
    return norm in _TOOLS_HEADINGS
# bullet: `- \`name\` — desc`  /  `* **name**: desc`
_BULLET_RE = re.compile(
    r"^\s*[-*]\s+[`*]*(" + _TOOL_NAME + r")[`*]*\s*[-—:]\s*(.+?)\s*$")
# table row: `| \`name\` | desc |`
_TABLE_RE = re.compile(
    r"^\s*\|\s*[`*]*(" + _TOOL_NAME + r")[`*]*\s*\|\s*(.+?)\s*\|")


def parse_server_json_tools(text: str) -> List[Tuple[str, str]]:
    """Tool (name, description) pairs declared in a server.json `tools` array."""
    try:
        data = json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return []
    out: List[Tuple[str, str]] = []
    for tool in (data.get("tools") if isinstance(data, dict) else None) or []:
        if isinstance(tool, dict) and tool.get("name"):
            out.append((str(tool["name"]), str(tool.get("description", ""))))
    return out


def parse_package_json_tools(text: str) -> List[Tuple[str, str]]:
    """Tool (name, description) pairs declared in a package.json — either a
    top-level `tools` array or an `mcp.tools` block (the conventions MCP npm
    packages use to declare their surface statically)."""
    try:
        data = json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    candidates = data.get("tools")
    if not candidates and isinstance(data.get("mcp"), dict):
        candidates = data["mcp"].get("tools")
    out: List[Tuple[str, str]] = []
    for tool in candidates or []:
        if isinstance(tool, dict) and tool.get("name"):
            out.append((str(tool["name"]), str(tool.get("description", ""))))
    return out


def parse_readme_tools(text: str) -> List[Tuple[str, str]]:
    """Tool (name, description) pairs from a README's "Tools" section (bullets or
    a markdown table). Conservative: only captured under a tools-ish heading, and
    only until the next heading — so install/usage prose never leaks in."""
    lines = (text or "").splitlines()
    out: List[Tuple[str, str]] = []
    in_section = False
    section_level = 0
    for line in lines:
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if _is_tools_heading(heading.group(2)):
                in_section, section_level = True, level
                continue
            if in_section and level <= section_level:
                in_section = False  # next sibling/parent heading ends the section
            continue
        if not in_section:
            continue
        m = _BULLET_RE.match(line) or _TABLE_RE.match(line)
        if m:
            name, desc = m.group(1), m.group(2).strip()
            if name.lower() in ("tool", "name"):  # table header row
                continue
            out.append((name, desc))
    return out


def declared_write_tools(texts: Dict[str, str]) -> List[ToolRecord]:
    """Write tools statically declared across the fetched manifest files, deduped
    by name, each carrying `declared_manifest` (medium-confidence) evidence."""
    pairs: List[Tuple[str, str]] = []
    pairs.extend(parse_server_json_tools(texts.get("server.json", "")))
    pairs.extend(parse_package_json_tools(texts.get("package.json", "")))
    pairs.extend(parse_readme_tools(texts.get("README", "")))

    out: List[ToolRecord] = []
    seen = set()
    for name, desc in pairs:
        if name in seen:
            continue
        blob = f"{name} {desc}"
        write_match = WRITE_RE.search(blob)
        if not write_match:
            continue  # read-only (or unclear) — not a declared write tool
        seen.add(name)
        out.append(ToolRecord(
            provider="manifest", server_id="", name=name,
            native_surface="manifest", description=desc, write_confidence="medium",
            evidence=[{"kind": "declared_manifest",
                       "value": write_match.group(0).lower(), "confidence": "medium"}],
        ))
    return out


def classify_manifest_record(rec: RegistryServerRecord, texts: Dict[str, str],
                             run_date: str) -> bool:
    """Ground statically-declared write tools onto a stdio record. Returns True
    if any were found. Records confidence_by_source['manifest'] either way so the
    record rotates out for a cadence window."""
    tools = declared_write_tools(texts)
    for tool in tools:
        tool.server_id = rec.identity
    if not tools:
        rec.confidence_by_source["manifest"] = {"confidence": "unknown", "date": run_date}
        return False

    # Keep any already-stored (e.g. verified) tools first; append declared ones
    # not already present, capped.
    have = {t.name for t in rec.tools}
    rec.tools = (rec.tools + [t for t in tools if t.name not in have])[:TOP_N_WRITE_TOOLS]

    existing = {(e.get("kind"), e.get("value"), e.get("confidence")) for e in rec.evidence}
    for tool in tools:
        for ev in tool.evidence:
            key = (ev.get("kind"), ev.get("value"), ev.get("confidence"))
            if key not in existing:
                rec.evidence.append(ev)
                existing.add(key)
    rec.confidence_by_source["manifest"] = {"confidence": "medium", "date": run_date}
    return True


# --- candidate selection + fetch (bounded like discovery, stdio repos) ----------

def raw_base(repo_url: str) -> Optional[str]:
    """GitHub raw content base for a repo URL (case-preserved), else None. Uses
    the shared canonical normalizer so URL-collapse rules live in one place."""
    owner_repo = github_owner_repo(repo_url)
    if not owner_repo:
        return None
    return f"https://raw.githubusercontent.com/{owner_repo[0]}/{owner_repo[1]}"


def manifest_urls(repo_url: str) -> Dict[str, str]:
    """Raw URLs for the three static manifest files (empty if not a GitHub repo)."""
    base = raw_base(repo_url)
    if not base:
        return {}
    return {
        "server.json": f"{base}/HEAD/server.json",
        "package.json": f"{base}/HEAD/package.json",
        "README": f"{base}/HEAD/README.md",
    }


def select_manifest_candidates(
    records: List[RegistryServerRecord],
    cap: int,
    last_parsed: Dict[str, str],
    cadence_days: int,
    run_date: str,
) -> List[RegistryServerRecord]:
    """Stdio (repo-only, GitHub) servers to static-parse this run. Write-priority
    with a reserved exploration slice; deterministic + rotating by last_parsed."""
    if cap <= 0:
        return []
    eligible = []
    for rec in records:
        if rec.remote_url or not raw_base(rec.repo_url):
            continue  # remote servers are discovery's job; need a GitHub repo to parse
        seen = last_parsed.get(rec.identity)
        if seen and days_between(seen, run_date) < cadence_days:
            continue
        eligible.append(rec)

    def priority_key(rec: RegistryServerRecord):
        claimed = 0 if is_claimed_write(rec) else 1
        never = 0 if rec.identity not in last_parsed else 1
        return (claimed, never, last_parsed.get(rec.identity, ""), rec.identity)

    explore = sorted(
        (r for r in eligible
         if r.identity not in last_parsed and evidence_tier(r.evidence) == "none"),
        key=lambda r: r.identity,
    )
    main = sorted(eligible, key=priority_key)

    chosen: List[RegistryServerRecord] = []
    ids = set()

    def fill(pool, limit):
        for rec in pool:
            if len(chosen) >= cap or limit <= 0:
                break
            if rec.identity in ids:
                continue
            chosen.append(rec)
            ids.add(rec.identity)
            limit -= 1

    fill(explore, int(cap * EXPLORATION_FRACTION))
    fill(main, cap)
    return chosen


def run_manifest_pass(ctx, candidates: List[RegistryServerRecord], run_date: str) -> Dict[str, str]:
    """Fetch each candidate's static manifest files via ctx (snapshots + issue
    logging + skip-network handled there) and ground declared write tools.
    Returns {identity: parsed_date} for every attempted record (so it rotates)."""
    parsed: Dict[str, str] = {}
    for rec in candidates:
        urls = manifest_urls(rec.repo_url)
        if not urls:
            continue
        texts: Dict[str, str] = {}
        for key, url in urls.items():
            body = ctx.fetch("manifest", url, label=f"{rec.identity}-{key}")
            if body:
                texts[key] = body
        parsed[rec.identity] = run_date
        if texts:
            classify_manifest_record(rec, texts, run_date)
    return parsed
