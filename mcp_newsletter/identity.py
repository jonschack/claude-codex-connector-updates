from __future__ import annotations

import re

from .utils import slugify

# The ONE canonical normalizer, shared by every tier (registry merge, manifest,
# grok radar, and P4 fusion). All cross-tier dedup/corroboration hinges on two
# different sources producing the same key for the same server, so the collapse
# rules (scheme, www., .git, /tree|blob/..., trailing slash, case) live here and
# nowhere else.


def _strip_repo_url(url: str) -> str:
    """Strip scheme, www., ref/path suffixes, .git, trailing slash — but preserve
    case (callers that need a case-sensitive host path build on this)."""
    s = url.strip()
    s = re.sub(r"^https?://", "", s, flags=re.I)
    s = re.sub(r"^www\.", "", s, flags=re.I)
    s = re.sub(r"/(tree|blob)/.*$", "", s)        # drop ref/path suffixes
    s = s.rstrip("/")
    return re.sub(r"\.git$", "", s, flags=re.I)


def canonical_repo(url: str) -> str:
    """`https://www.GitHub.com/Acme/Solo.git/tree/main` -> `github.com/acme/solo`."""
    if not url:
        return ""
    return "/".join(p for p in _strip_repo_url(url).split("/") if p).lower()


def github_owner_repo(url: str):
    """`(owner, repo)` with original case for a GitHub URL, else None. Shares the
    one strip pipeline with canonical_repo so the collapse rules live in one place."""
    if not url:
        return None
    parts = [p for p in _strip_repo_url(url).split("/") if p]
    if len(parts) < 3 or parts[0].lower() != "github.com":
        return None
    return parts[1], parts[2]


def canonical_key(
    *,
    official_name: str = "",
    repo_url: str = "",
    subpath: str = "",
    source: str = "",
    source_id: str = "",
    name: str = "",
) -> str:
    """Canonical identity for a server, precedence: reverse-DNS official name >
    normalized repo (+subpath for monorepos) > `source:slug` fallback."""
    if official_name:
        return official_name.lower()
    repo = canonical_repo(repo_url)
    if repo:
        if subpath:
            return f"repo:{repo}#{subpath.strip('/').lower()}"
        return f"repo:{repo}"
    return f"{source}:{slugify(source_id or name)}"
