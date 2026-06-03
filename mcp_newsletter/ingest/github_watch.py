from __future__ import annotations

import json
from typing import Dict, List, Tuple

# P4 momentum: track star/release deltas for FRONTIER CANDIDATES ONLY (verified-
# write + write-priority top-N) — never all ~30k repos. Batched via a single
# GraphQL call (≤100 repos) to stay within rate limits; degrade to no-momentum
# (never crash) when the call fails or is throttled.

GITHUB_GRAPHQL_BATCH = 100


def build_graphql_query(repos: List[Tuple[str, str]]) -> str:
    """One GraphQL query fetching stargazerCount + latest release for up to
    GITHUB_GRAPHQL_BATCH (owner, name) repos, aliased r0..rN."""
    fields = (
        "{ nameWithOwner stargazerCount "
        "releases(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) "
        "{ nodes { tagName createdAt } } }"
    )
    parts = []
    for i, (owner, name) in enumerate(repos[:GITHUB_GRAPHQL_BATCH]):
        o = owner.replace('"', '\\"')
        n = name.replace('"', '\\"')
        parts.append(f'r{i}: repository(owner: "{o}", name: "{n}") {fields}')
    return "query {\n  " + "\n  ".join(parts) + "\n}"


def parse_graphql(json_text: str) -> Dict[str, dict]:
    """Parse the GraphQL response into {nameWithOwner: {stars, latest_release,
    released_at}}. Null repos (deleted/renamed/inaccessible) are skipped — never
    raises."""
    try:
        data = json.loads(json_text or "")
    except (json.JSONDecodeError, TypeError):
        return {}
    root = (data.get("data") if isinstance(data, dict) else None) or {}
    out: Dict[str, dict] = {}
    for repo in root.values():
        if not isinstance(repo, dict) or not repo.get("nameWithOwner"):
            continue
        nodes = ((repo.get("releases") or {}).get("nodes")) or []
        latest = nodes[0] if nodes else {}
        out[repo["nameWithOwner"].lower()] = {
            "stars": int(repo.get("stargazerCount", 0) or 0),
            "latest_release": latest.get("tagName", ""),
            "released_at": latest.get("createdAt", ""),
        }
    return out


def momentum(prev: Dict[str, dict], cur: Dict[str, dict]) -> Dict[str, dict]:
    """Per-repo deltas vs the prior snapshot: star growth + whether a new release
    appeared. A repo absent from `prev` (first sighting) reports 0 star delta but
    flags the release if present, so brand-new candidates don't spike falsely."""
    out: Dict[str, dict] = {}
    for key, now in cur.items():
        before = prev.get(key) or {}
        star_delta = now.get("stars", 0) - int(before.get("stars", now.get("stars", 0)))
        # Only a CHANGE vs a known baseline is a new release — a first-sighting
        # repo has no baseline, so its pre-existing release isn't "new".
        new_release = bool(before) and bool(now.get("latest_release")) and (
            now.get("latest_release") != before.get("latest_release"))
        out[key] = {"star_delta": max(0, star_delta), "new_release": new_release}
    return out
