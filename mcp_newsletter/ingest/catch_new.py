from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Set

from ..identity import canonical_key, github_owner_repo
from ..registries.base import RegistryServerRecord
from ..registries.merge import build_alias_map, merge_entries
from .github_watch import build_graphql_query, momentum, parse_graphql
from .official_incremental import parse_incremental
from .package_watch import parse_npm_search, parse_pypi_rss

# P4 orchestration: additively fold catch-new sources into the merged record set
# (the full periodic pull still owns liveness/delisting) and compute candidate-only
# github momentum. All network is best-effort + env-gated; failures degrade to
# no-op, never crash the daily run.

OFFICIAL_BASE = "https://registry.modelcontextprotocol.io/v0.1/servers"
NPM_SEARCH_URL = "https://registry.npmjs.org/-/v1/search?text=keywords:mcp&sort=date&size=100"
PYPI_RSS_URL = "https://pypi.org/rss/packages.xml"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
INCREMENTAL_PAGE_LIMIT = 100   # API caps limit at 100
INCREMENTAL_MAX_PAGES = 20     # bound the catch-up; full pull backstops overflow


def augment_catch_new(ctx, current: Dict[str, RegistryServerRecord], meta,
                      run_date: str) -> Set[str]:
    """Fold incremental + package-watch sources into `current` ADDITIVELY (new
    identities only; the full pull owns existing rows), advance the official
    cursor, apply deletion tombstones, and return the set of NEW identities (the
    select_discovery_candidates priority-1 seam). No-op when skip_network."""
    new_ids: Set[str] = set()
    if getattr(ctx, "skip_network", False):
        return new_ids

    extra: List = []
    deleted: List[str] = []

    if os.environ.get("MCP_NEWSLETTER_OFFICIAL_INCREMENTAL", "1") != "0":
        base = os.environ.get("MCP_NEWSLETTER_OFFICIAL_URL", OFFICIAL_BASE)
        since = meta.official_cursor
        # Page through the updated_since window (bounded) so changes beyond the
        # first page aren't silently dropped; the periodic full pull backstops any
        # overflow past INCREMENTAL_MAX_PAGES.
        cursor = ""
        fetched_any = False
        for page in range(INCREMENTAL_MAX_PAGES):
            params = [f"limit={INCREMENTAL_PAGE_LIMIT}"]
            if since:
                params.append(f"updated_since={since}")
            if cursor:
                params.append(f"cursor={cursor}")
            url = base + "?" + "&".join(params)
            body = ctx.fetch("catch_new", url, f"official-incremental-{page}")
            if not body:
                break
            ents, cursor, dels = parse_incremental(body)
            extra.extend(ents)
            deleted.extend(dels)
            fetched_any = True
            if not cursor:
                break
        if fetched_any:
            meta.official_cursor = run_date  # advance high-watermark

    if os.environ.get("MCP_NEWSLETTER_PACKAGE_WATCH", "0") == "1":
        nb = ctx.fetch("catch_new", NPM_SEARCH_URL, "npm-search")
        if nb:
            extra.extend(parse_npm_search(nb))
        pb = ctx.fetch("catch_new", PYPI_RSS_URL, "pypi-rss")
        if pb:
            extra.extend(parse_pypi_rss(pb))

    if extra:
        merged = merge_entries(extra, build_alias_map(list(current.values())))
        for rec in merged:
            if rec.identity not in current:
                current[rec.identity] = rec
                new_ids.add(rec.identity)
                # stamp as genuinely-new now, so it isn't backfill-suppressed when
                # the full pull picks it up next run.
                meta.first_seen.setdefault(rec.identity, run_date)

    # Tombstones are the only incremental delete. A status=deleted record removes
    # the server even if this run's full pull happened to still list it — an
    # explicit deletion is authoritative over a stale full-pull listing. The key
    # matches the merge identity (both use official_name.lower()).
    for name in deleted:
        current.pop(canonical_key(official_name=name), None)

    return new_ids


def _github_post(query: str, token: str, timeout: int = 20) -> str:
    """POST a GraphQL query to the GitHub API (it requires POST; ctx.fetch is GET
    only). Returns the response body, or "" on any failure. Isolated so tests can
    monkeypatch it."""
    payload = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        GITHUB_GRAPHQL_URL, data=payload, method="POST",
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "mcp-newsletter-frontier"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def github_momentum_for_candidates(candidates: List[RegistryServerRecord],
                                   meta, *, skip_network: bool = False) -> Dict[str, float]:
    """Candidate-only github momentum (needs GITHUB_TOKEN). Returns {identity ->
    momentum in [0,1]} and updates meta.github_stars. Degrades to {} on any
    failure — momentum is a bonus, never a requirement. NEVER scans all repos:
    only the bounded candidate list passed in, batched ≤100 per GraphQL call."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token or skip_network or not candidates:
        return {}

    # map candidates with a github repo to (owner, name); keep the identity link
    repo_to_identity: Dict[str, str] = {}
    repos = []
    for rec in candidates:
        owner_repo = github_owner_repo(rec.repo_url)
        if not owner_repo:
            continue
        repo_to_identity[f"{owner_repo[0]}/{owner_repo[1]}".lower()] = rec.identity
        repos.append(owner_repo)
    if not repos:
        return {}

    body = _github_post(build_graphql_query(repos), token)
    if not body:
        return {}
    snapshot = parse_graphql(body)
    # prev snapshot carries stars AND latest_release, so new_release is a real
    # cross-run delta (not stuck true every run).
    deltas = momentum(meta.github_snapshot or {}, snapshot)

    out: Dict[str, float] = {}
    for repo_key, info in snapshot.items():
        meta.github_snapshot[repo_key] = info
        identity = repo_to_identity.get(repo_key)
        if not identity:
            continue
        d = deltas.get(repo_key, {})
        # normalize: star velocity (capped) + a fixed bump for a fresh release
        m = min(1.0, d.get("star_delta", 0) / 100.0) * 0.7 + (0.3 if d.get("new_release") else 0.0)
        if m > 0:
            out[identity] = round(min(1.0, m), 4)
    return out
