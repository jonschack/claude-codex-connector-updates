from __future__ import annotations

import json
from typing import List, Tuple

from ..registries.base import RawRegistryEntry

# P4 catch-new: poll the official registry's `updated_since` cursor so a newly
# published/updated server surfaces the NEXT run instead of waiting for the full
# periodic pull. ADDITIVE-merge only — incremental absence is NOT a delist (the
# full pull owns liveness/delisting); the sole incremental delete is an explicit
# `status=deleted` tombstone.

PROVIDER = "official"


def parse_incremental(json_text: str) -> Tuple[List[RawRegistryEntry], str, List[str]]:
    """Parse one `updated_since` page. Returns (entries, next_cursor, deleted_names).
    `deleted_names` are tombstones (status=deleted) — the only incremental delete."""
    try:
        data = json.loads(json_text or "")
    except (json.JSONDecodeError, TypeError):
        return [], "", []
    if not isinstance(data, dict):
        return [], "", []

    entries: List[RawRegistryEntry] = []
    deleted: List[str] = []
    for entry in data.get("servers", []):
        server = entry.get("server") or entry
        official_meta = (entry.get("_meta") or {}).get(
            "io.modelcontextprotocol.registry/official") or {}
        name = server.get("name", "")
        if not name:
            continue
        if official_meta.get("status") == "deleted":
            deleted.append(name)
            continue
        repo = server.get("repository") or {}
        remotes = server.get("remotes") or []
        entries.append(RawRegistryEntry(
            source=PROVIDER,
            source_id=name,
            official_name=name,
            name=server.get("title") or name.split("/")[-1] or name,
            description=server.get("description", ""),
            repo_url=repo.get("url", ""),
            subpath=repo.get("subfolder", "") or "",
            remote_url=(remotes[0].get("url", "") if remotes else ""),
            tags=list((server.get("_meta") or {}).get("tags", [])),
            last_updated=official_meta.get("updatedAt", ""),
            raw=entry,
        ))
    next_cursor = (data.get("metadata") or {}).get("nextCursor") or ""
    return entries, next_cursor, deleted
