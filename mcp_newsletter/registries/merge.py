from __future__ import annotations

import re
from typing import Dict, List

from ..utils import slugify
from .base import RawRegistryEntry, RegistryServerRecord


def _normalize_repo(repo_url: str) -> str:
    """github.com/acme/solo  (host lowercased, scheme/.git/trailing slash stripped)."""
    if not repo_url:
        return ""
    url = repo_url.strip()
    url = re.sub(r"^https?://", "", url, flags=re.I)
    url = url.rstrip("/")
    url = re.sub(r"\.git$", "", url, flags=re.I)
    # drop /tree/<ref>/... or /blob/... suffixes
    url = re.sub(r"/(tree|blob)/.*$", "", url)
    return "/".join(p for p in url.split("/") if p).lower()


def identity(entry: RawRegistryEntry) -> str:
    if entry.official_name:
        return entry.official_name.lower()
    repo = _normalize_repo(entry.repo_url)
    if repo:
        if entry.subpath:
            return f"repo:{repo}#{entry.subpath.strip('/').lower()}"
        return f"repo:{repo}"
    # Prefer source_id (the registry's UNIQUE key, e.g. Smithery qualifiedName,
    # mcp.so uuid) over the display name, which collides across distinct servers.
    return f"{entry.source}:{slugify(entry.source_id or entry.name)}"


def _alias_keys(entry: RawRegistryEntry) -> List[str]:
    """High-specificity alias keys only — never remote_url."""
    keys = []
    if entry.official_name:
        keys.append(entry.official_name.lower())
    repo = _normalize_repo(entry.repo_url)
    if repo:
        keys.append(f"repo:{repo}#{entry.subpath.strip('/').lower()}" if entry.subpath else f"repo:{repo}")
    return keys


def _resolve_identity(entry: RawRegistryEntry, aliases: Dict[str, str]) -> str:
    for key in _alias_keys(entry):
        if key in aliases:
            return aliases[key]
    return identity(entry)


def merge_entries(entries: List[RawRegistryEntry], aliases: Dict[str, str]) -> List[RegistryServerRecord]:
    by_id: Dict[str, RegistryServerRecord] = {}
    for entry in entries:
        ident = _resolve_identity(entry, aliases)
        rec = by_id.get(ident)
        source_row = {
            "source": entry.source,
            "source_id": entry.source_id,
            "source_url": entry.source_url,
            "tags": sorted(set(entry.tags)),
            "last_updated": entry.last_updated,
        }
        if rec is None:
            rec = RegistryServerRecord(
                identity=ident,
                name=entry.name,
                description=entry.description,
                repo_url=entry.repo_url,
                remote_url=entry.remote_url,
                sources=[source_row],
                tags=list(entry.tags),
            )
            by_id[ident] = rec
            continue
        rec.sources.append(source_row)
        rec.tags = sorted(set(rec.tags + entry.tags))
        if len(entry.description) > len(rec.description):
            rec.description = entry.description
        if not rec.repo_url and entry.repo_url:
            rec.repo_url = entry.repo_url
        if not rec.remote_url and entry.remote_url:
            rec.remote_url = entry.remote_url
    return [by_id[k] for k in sorted(by_id)]


def build_alias_map(records: List[RegistryServerRecord]) -> Dict[str, str]:
    """Persisted next run: every high-specificity key -> canonical identity."""
    aliases: Dict[str, str] = {}
    for rec in records:
        aliases[rec.identity] = rec.identity
        repo = _normalize_repo(rec.repo_url)
        if repo:
            aliases.setdefault(f"repo:{repo}", rec.identity)
    return aliases
