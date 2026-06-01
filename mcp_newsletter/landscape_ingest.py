from __future__ import annotations

import re
from typing import Any, Dict, List

_REPORTABLE = {"medium", "high"}
_GITHUB_RE = re.compile(r"https?://github\.com/", re.I)


def normalize_vendor_record(v: Dict[str, Any], run_date: str) -> Dict[str, Any]:
    """Map a vendor ServerRecord dict into the landscape record shape.
    Vendor write-capability is catalog/description-derived, recorded under
    confidence_by_source['catalog'] only when reportable (so evidence_tier
    yields claimed_description, never a false verified_tools)."""
    provider = v.get("provider", "")
    server_id = v.get("server_id", "")
    source_urls: List[str] = v.get("source_urls") or []
    repo_url = next((u for u in source_urls if _GITHUB_RE.match(u or "")), "")
    wc = v.get("write_confidence", "unknown")
    cbs: Dict[str, Any] = {}
    if wc in _REPORTABLE:
        cbs["catalog"] = {"confidence": wc, "date": run_date}
    return {
        "identity": f"{provider}:{server_id}",
        "name": v.get("name", ""),
        "description": v.get("description", ""),
        "repo_url": repo_url,
        "remote_url": v.get("remote_url", ""),
        "sources": [{"source": provider}],
        "capabilities": list(v.get("capabilities") or []),
        "tags": list(v.get("capabilities") or []),
        "write_confidence": wc,
        "evidence": list(v.get("evidence") or []),
        "confidence_by_source": cbs,
    }
