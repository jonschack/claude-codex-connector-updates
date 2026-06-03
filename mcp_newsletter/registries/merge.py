from __future__ import annotations

from typing import Dict, List

from ..identity import canonical_key, canonical_repo
from .base import RawRegistryEntry, RegistryServerRecord

# The canonical normalizer lives in mcp_newsletter.identity (shared by all tiers).
_normalize_repo = canonical_repo


def identity(entry: RawRegistryEntry) -> str:
    # Prefer source_id (the registry's UNIQUE key, e.g. Smithery qualifiedName,
    # mcp.so uuid) over the display name, which collides across distinct servers.
    return canonical_key(
        official_name=entry.official_name,
        repo_url=entry.repo_url,
        subpath=entry.subpath,
        source=entry.source,
        source_id=entry.source_id,
        name=entry.name,
    )


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
