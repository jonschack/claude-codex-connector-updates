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
    parts = url.split("/")
    if parts:
        parts[0] = parts[0].lower()  # host only
    return "/".join(p for p in parts if p).lower()


def identity(entry: RawRegistryEntry) -> str:
    if entry.official_name:
        return entry.official_name
    repo = _normalize_repo(entry.repo_url)
    if repo:
        if entry.subpath:
            return f"repo:{repo}#{entry.subpath.strip('/')}"
        return f"repo:{repo}"
    return f"{entry.source}:{slugify(entry.name or entry.source_id)}"
