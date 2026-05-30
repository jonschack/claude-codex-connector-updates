from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class RawRegistryEntry:
    """One server as seen in ONE registry, before dedup."""
    source: str
    source_id: str
    name: str
    description: str = ""
    repo_url: str = ""
    remote_url: str = ""
    subpath: str = ""
    official_name: str = ""          # reverse-DNS name if the source provides one
    tags: List[str] = field(default_factory=list)
    last_updated: str = ""
    source_url: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegistryServerRecord:
    """Canonical, deduped server across registries."""
    identity: str
    name: str
    description: str = ""
    repo_url: str = ""
    remote_url: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    write_confidence: str = "unknown"
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    # confidence remembered per evidence source: {"tools": {"confidence","date"}, "catalog": {...}}
    confidence_by_source: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity,
            "name": self.name,
            "description": self.description,
            "repo_url": self.repo_url,
            "remote_url": self.remote_url,
            "sources": sorted(self.sources, key=lambda s: s.get("source", "")),
            "capabilities": sorted(set(self.capabilities)),
            "tags": sorted(set(self.tags)),
            "write_confidence": self.write_confidence,
            "evidence": self.evidence,
            "confidence_by_source": self.confidence_by_source,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)

    @classmethod
    def from_jsonl(cls, line: str) -> "RegistryServerRecord":
        data = json.loads(line)
        return cls(
            identity=data["identity"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            repo_url=data.get("repo_url", ""),
            remote_url=data.get("remote_url", ""),
            sources=data.get("sources", []),
            capabilities=data.get("capabilities", []),
            tags=data.get("tags", []),
            write_confidence=data.get("write_confidence", "unknown"),
            evidence=data.get("evidence", []),
            confidence_by_source=data.get("confidence_by_source", {}),
        )


@dataclass
class RegistryCollection:
    entries: List[RawRegistryEntry] = field(default_factory=list)
    # source name -> succeeded this run (False freezes liveness for that source)
    source_ok: Dict[str, bool] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)


# A collector takes the CollectContext and returns its raw entries.
RegistrySource = Callable[[Any], List[RawRegistryEntry]]
