"""
Pure analysis functions for MCP landscape measurement (Loop 1).

No network I/O, no datetime.now(), no time, no random. Any "today" is
passed in as a string argument.

Theme taxonomy note: DEFAULT_TAXONOMY uses plain English keyword matching
against name + description + tags. This is a known limitation — non-English
server descriptions will score poorly. The taxonomy is data, not inline
regex, enabling future localisation without code changes.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Classifier helpers (mirror of classifier.py without importing it to keep
# landscape.py self-contained as a pure analysis module)
# ---------------------------------------------------------------------------

_RANK: Dict[str, int] = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
_REPORTABLE = {"medium", "high"}


def _is_reportable(confidence: str) -> bool:
    return confidence in _REPORTABLE


# ---------------------------------------------------------------------------
# I1 — evidence_tier
# ---------------------------------------------------------------------------

def evidence_tier(record: Dict[str, Any]) -> str:
    """Return the evidence tier for a record's write-capability claim.

    Tier priority (highest first):
      verified_tools   — confidence_by_source["tools"] is reportable
      annotation       — any evidence item with kind=="mcp_annotation" is reportable
      claimed_description — confidence_by_source["catalog"] is reportable
      none             — not write-capable (write_confidence not reportable)

    Parameters
    ----------
    record:
        A dict shaped like RegistryServerRecord.to_dict().

    Returns
    -------
    One of "verified_tools", "annotation", "claimed_description", "none".
    """
    cbs: Dict[str, Dict[str, str]] = record.get("confidence_by_source") or {}

    # verified_tools: tools source is reportable
    tools_entry = cbs.get("tools") or {}
    if _is_reportable(tools_entry.get("confidence", "unknown")):
        return "verified_tools"

    # annotation: any evidence item with kind == "mcp_annotation" is reportable
    evidence: List[Dict[str, Any]] = record.get("evidence") or []
    for item in evidence:
        if item.get("kind") == "mcp_annotation" and _is_reportable(
            item.get("confidence", "unknown")
        ):
            return "annotation"

    # claimed_description: catalog source is reportable
    catalog_entry = cbs.get("catalog") or {}
    if _is_reportable(catalog_entry.get("confidence", "unknown")):
        return "claimed_description"

    return "none"


# ---------------------------------------------------------------------------
# I2 — coverage
# ---------------------------------------------------------------------------

def coverage(
    summary: Dict[str, Any],
    known_totals: Dict[str, Optional[int]],
) -> Dict[str, Any]:
    """Compute coverage accounting from a registry_summary-shaped dict.

    Parameters
    ----------
    summary:
        Shape of registry_summary.json:
        {
          "enabled_sources": [...],
          "source_ok": {src: bool},
          "per_source": {src: int},        # deduplicated pulled counts
          "per_source_raw": {src: int},    # raw pulled counts (optional)
          "issues": [...],
        }
    known_totals:
        {source: best_known_total_estimate} — use None for unknown.

    Returns
    -------
    {
      "sources_attempted": [...],
      "sources_succeeded": [...],
      "sources_failed": [...],
      "per_source": {
        src: {
          "pulled": int,
          "known_estimate": int | None,
          "coverage_pct": float | None,   # capped at 100.0
        }
      },
      "overall_coverage_pct": float | None,
      "notes": [...],
    }
    """
    enabled: List[str] = list(summary.get("enabled_sources") or [])
    source_ok: Dict[str, bool] = summary.get("source_ok") or {}
    per_source_counts: Dict[str, int] = summary.get("per_source") or {}

    attempted = list(enabled)
    succeeded = [s for s in attempted if source_ok.get(s, False)]
    failed = [s for s in attempted if not source_ok.get(s, False)]

    per_src_out: Dict[str, Dict[str, Any]] = {}
    for src in attempted:
        pulled = per_source_counts.get(src, 0)
        known = known_totals.get(src)
        if known is not None and known > 0:
            cov_pct: Optional[float] = min(100.0, round(pulled / known * 100.0, 4))
        elif known == 0:
            cov_pct = 100.0 if pulled == 0 else None
        else:
            cov_pct = None
        per_src_out[src] = {
            "pulled": pulled,
            "known_estimate": known,
            "coverage_pct": cov_pct,
        }

    # overall: sum(pulled) / sum(known) for succeeded sources only, where known exists
    total_pulled = 0
    total_known = 0
    has_known = False
    for src in succeeded:
        d = per_src_out[src]
        total_pulled += d["pulled"]
        if d["known_estimate"] is not None:
            total_known += d["known_estimate"]
            has_known = True

    if has_known and total_known > 0:
        overall: Optional[float] = min(100.0, round(total_pulled / total_known * 100.0, 4))
    elif has_known and total_known == 0:
        overall = 100.0 if total_pulled == 0 else None
    else:
        overall = None

    notes: List[str] = []
    for src in enabled:
        if src not in succeeded:
            notes.append(f"Source '{src}' was enabled but did not succeed.")

    return {
        "sources_attempted": attempted,
        "sources_succeeded": succeeded,
        "sources_failed": failed,
        "per_source": per_src_out,
        "overall_coverage_pct": overall,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# I4 — estimate_residual_dups
# ---------------------------------------------------------------------------

def _normalize_repo_url(url: str) -> str:
    """Lowercase, strip scheme, strip .git suffix, strip trailing slash."""
    if not url:
        return ""
    u = url.lower()
    # strip scheme (https://, http://, git://, etc.)
    u = re.sub(r"^[a-z][a-z0-9+\-.]*://", "", u)
    # strip www.
    u = re.sub(r"^www\.", "", u)
    # strip trailing .git
    if u.endswith(".git"):
        u = u[:-4]
    # strip trailing slash
    u = u.rstrip("/")
    return u


def _normalize_name(name: str) -> str:
    """Lowercase, remove all non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def estimate_residual_dups(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect records with different identities that are likely the same server.

    Matching criteria (applied with OR logic):
    - Normalised repo_url (lowercased, scheme stripped, .git stripped, trailing slash stripped)
    - Normalised name (lowercased, non-alnum removed)

    A secondary-key collision between two distinct identities → suspected duplicates.

    Parameters
    ----------
    records:
        List of dicts shaped like RegistryServerRecord.to_dict().

    Returns
    -------
    {
      "unique_identities": int,
      "suspected_dup_clusters": int,
      "suspected_extra_records": int,   # sum(cluster_size - 1)
      "examples": [[id1, id2, ...], ...]  # up to 5 clusters
    }
    """
    # Build secondary-key → set of identities
    repo_map: Dict[str, set] = {}
    name_map: Dict[str, set] = {}

    for rec in records:
        identity: str = rec.get("identity", "")
        repo = _normalize_repo_url(rec.get("repo_url", ""))
        name = _normalize_name(rec.get("name", ""))

        if repo:
            repo_map.setdefault(repo, set()).add(identity)
        if name:
            name_map.setdefault(name, set()).add(identity)

    # Collect clusters of identities that share a secondary key
    # Use union-find to merge overlapping clusters
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    all_ids = {rec.get("identity", "") for rec in records}

    for key_map in (repo_map, name_map):
        for ids in key_map.values():
            ids_list = list(ids)
            if len(ids_list) > 1:
                for i in range(1, len(ids_list)):
                    union(ids_list[0], ids_list[i])

    # Group by root
    clusters: Dict[str, List[str]] = {}
    for identity in all_ids:
        root = find(identity)
        clusters.setdefault(root, []).append(identity)

    # Only keep clusters with >1 member
    dup_clusters = {root: sorted(ids) for root, ids in clusters.items() if len(ids) > 1}

    suspected_extra = sum(len(ids) - 1 for ids in dup_clusters.values())
    examples = sorted(dup_clusters.values(), key=lambda ids: (-len(ids), ids[0]))[:5]

    return {
        "unique_identities": len(all_ids),
        "suspected_dup_clusters": len(dup_clusters),
        "suspected_extra_records": suspected_extra,
        "examples": examples,
    }


# ---------------------------------------------------------------------------
# I7 — Taxonomy as DATA + assign_themes
# ---------------------------------------------------------------------------

# DEFAULT_TAXONOMY: ordered list of (theme_name, [keywords]) in priority order
# (most-consequential first). Keywords are plain substrings matched
# case-insensitively against "name description tags_joined".
#
# Limitation: keywords are English-only. Non-English server descriptions
# will not match and will fall back to "other".
DEFAULT_TAXONOMY: List[Tuple[str, List[str]]] = [
    (
        "payments/finance/crypto",
        [
            "payment", "payments", "stripe", "billing", "invoice", "invoicing",
            "finance", "financial", "accounting", "crypto", "cryptocurrency",
            "bitcoin", "ethereum", "wallet", "transaction", "transactions",
            "bank", "banking", "payroll", "revenue", "expense", "expenses",
            "ledger", "tax", "defi", "nft",
        ],
    ),
    (
        "deploy/cloud/infra",
        [
            "deploy", "deployment", "deployments", "kubernetes", "k8s",
            "docker", "container", "containers", "terraform", "pulumi",
            "aws", "gcp", "azure", "cloud", "infra", "infrastructure",
            "serverless", "lambda", "ci/cd", "cicd", "pipeline", "helm",
            "devops", "observability", "monitoring", "alerting", "logs",
            "logging", "metrics", "prometheus", "grafana",
        ],
    ),
    (
        "code-execution",
        [
            "execute", "execution", "run code", "sandbox", "repl",
            "jupyter", "notebook", "python interpreter", "eval",
            "code runner", "shell", "bash", "script", "scripting",
        ],
    ),
    (
        "data/database",
        [
            "database", "db", "sql", "mysql", "postgres", "postgresql",
            "sqlite", "mongodb", "redis", "elasticsearch", "query",
            "queries", "data warehouse", "bigquery", "snowflake",
            "dbt", "analytics", "bi", "etl", "data pipeline",
            "vector database", "vector db", "pinecone", "weaviate",
            "chroma", "qdrant",
        ],
    ),
    (
        "devtools/git",
        [
            "git", "github", "gitlab", "bitbucket", "code review",
            "pull request", "pr", "issue tracker", "jira", "linear",
            "linting", "lint", "test", "testing", "ci", "coverage",
            "debugger", "debugging", "ide", "editor", "vscode",
            "refactor", "static analysis",
        ],
    ),
    (
        "browser/computer",
        [
            "browser", "web browser", "chrome", "firefox", "selenium",
            "playwright", "puppeteer", "scraping", "scraper", "crawl",
            "crawling", "screenshot", "automation", "computer use",
            "desktop", "gui", "ui automation", "click", "form fill",
        ],
    ),
    (
        "comms/social",
        [
            "email", "mail", "smtp", "gmail", "outlook", "slack",
            "discord", "teams", "telegram", "whatsapp", "sms",
            "notification", "notifications", "chat", "messaging",
            "social media", "twitter", "x.com", "linkedin", "reddit",
            "mastodon", "bluesky", "rss", "feed",
        ],
    ),
    (
        "files/docs/storage",
        [
            "file", "files", "filesystem", "storage", "s3", "blob",
            "document", "documents", "pdf", "word", "docx", "spreadsheet",
            "excel", "csv", "json", "xml", "drive", "google drive",
            "dropbox", "onedrive", "box", "upload", "download",
            "read file", "write file", "directory",
        ],
    ),
    (
        "calendar/booking",
        [
            "calendar", "calendars", "schedule", "scheduling", "booking",
            "appointment", "appointments", "meeting", "meetings",
            "event", "events", "google calendar", "outlook calendar",
            "cal.com", "availability",
        ],
    ),
]


def assign_themes(
    record: Dict[str, Any],
    taxonomy: List[Tuple[str, List[str]]] = DEFAULT_TAXONOMY,
) -> Dict[str, Any]:
    """Assign taxonomy themes to a record.

    Matching is a case-insensitive substring search on the concatenated
    text of name + description + tags. The first matching theme in
    priority order becomes the primary theme. All matching themes are
    listed in "all".

    Parameters
    ----------
    record:
        Dict shaped like RegistryServerRecord.to_dict().
    taxonomy:
        Ordered list of (theme_name, [keywords]). Defaults to DEFAULT_TAXONOMY.

    Returns
    -------
    {"primary": str, "all": [str]}
        primary: first matching theme by priority order, or "other" if none.
        all: all matching themes in priority order; may be empty (→ ["other"]).
    """
    name: str = record.get("name") or ""
    description: str = record.get("description") or ""
    tags: List[str] = record.get("tags") or []
    haystack = (name + " " + description + " " + " ".join(tags)).lower()

    matched: List[str] = []
    for theme_name, keywords in taxonomy:
        for kw in keywords:
            if kw.lower() in haystack:
                matched.append(theme_name)
                break  # only need one keyword to match a theme

    primary = matched[0] if matched else "other"
    return {"primary": primary, "all": matched if matched else []}


# ---------------------------------------------------------------------------
# I8 — rank_servers
# ---------------------------------------------------------------------------

_TIER_RANK: Dict[str, int] = {
    "verified_tools": 3,
    "annotation": 2,
    "claimed_description": 1,
    "none": 0,
}


def rank_servers(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return records sorted best-first by:

    (tier_rank DESC, write_conf_rank DESC, source_count DESC, identity ASC)

    This is a stable, deterministic sort with no cherry-picking.

    Parameters
    ----------
    records:
        List of dicts shaped like RegistryServerRecord.to_dict().

    Returns
    -------
    New list (input is not mutated) sorted best-first.
    """

    def sort_key(rec: Dict[str, Any]) -> Tuple:
        tier = evidence_tier(rec)
        tier_r = _TIER_RANK.get(tier, 0)
        wc = rec.get("write_confidence", "unknown")
        wc_r = _RANK.get(wc, 0)
        src_count = len(rec.get("sources") or [])
        identity = rec.get("identity") or ""
        # DESC for numeric fields → negate; ASC for identity → keep as-is
        return (-tier_r, -wc_r, -src_count, identity)

    return sorted(records, key=sort_key)


# ---------------------------------------------------------------------------
# I9 — wilson_interval and summarize
# ---------------------------------------------------------------------------

def wilson_interval(
    successes: int,
    n: int,
    z: float = 1.96,
) -> Tuple[float, float]:
    """Standard Wilson score confidence interval for a proportion.

    Parameters
    ----------
    successes:
        Number of positive outcomes.
    n:
        Total trials.
    z:
        Z-score (default 1.96 → 95 % CI).

    Returns
    -------
    (low, high) both in [0, 1].
    Returns (0.0, 0.0) when n == 0.
    """
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denominator
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    return (low, high)


def summarize(
    records: List[Dict[str, Any]],
    coverage_obj: Dict[str, Any],
    snapshot_date: str,
    validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce a metrics summary dict for the landscape snapshot.

    Parameters
    ----------
    records:
        List of dicts shaped like RegistryServerRecord.to_dict().
    coverage_obj:
        The dict returned by coverage().
    snapshot_date:
        ISO date string (e.g. "2026-05-31"). Never computed internally.
    validation:
        Optional dict with precision/recall/F1 from classifier validation;
        included verbatim when provided.

    Returns
    -------
    {
      "snapshot_date": str,
      "total_records": int,
      "by_tier": {tier: count},
      "write_capable": {
        "total": int,
        "verified_tools": int,
        "annotation": int,
        "claimed_description": int,
      },
      "themes_primary": {theme: count},   # mutually exclusive, sums to total_records
      "themes_overlap": {theme: count},   # all matches, sums >= total_records
      "coverage": coverage_obj,
      "residual_dups": estimate_residual_dups(records),
      "validation": validation | None,
    }
    """
    total = len(records)

    # by_tier counts
    by_tier: Dict[str, int] = {
        "verified_tools": 0,
        "annotation": 0,
        "claimed_description": 0,
        "none": 0,
    }
    write_capable = {
        "total": 0,
        "verified_tools": 0,
        "annotation": 0,
        "claimed_description": 0,
    }

    # themes
    all_theme_names = [t[0] for t in DEFAULT_TAXONOMY] + ["other"]
    themes_primary: Dict[str, int] = {t: 0 for t in all_theme_names}
    themes_overlap: Dict[str, int] = {t: 0 for t in all_theme_names}

    for rec in records:
        tier = evidence_tier(rec)
        by_tier[tier] = by_tier.get(tier, 0) + 1
        if tier != "none":
            write_capable["total"] += 1
            write_capable[tier] = write_capable.get(tier, 0) + 1  # type: ignore[assignment]

        theme_result = assign_themes(rec)
        primary = theme_result["primary"]
        themes_primary[primary] = themes_primary.get(primary, 0) + 1
        for th in theme_result["all"]:
            themes_overlap[th] = themes_overlap.get(th, 0) + 1
        if not theme_result["all"]:
            themes_overlap["other"] = themes_overlap.get("other", 0) + 1

    return {
        "snapshot_date": snapshot_date,
        "total_records": total,
        "by_tier": by_tier,
        "write_capable": write_capable,
        "themes_primary": themes_primary,
        "themes_overlap": themes_overlap,
        "coverage": coverage_obj,
        "residual_dups": estimate_residual_dups(records),
        "validation": validation,
    }
