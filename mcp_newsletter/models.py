from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


JsonDict = Dict[str, Any]


@dataclass
class ToolRecord:
    provider: str
    server_id: str
    name: str
    native_surface: str
    description: str = ""
    input_schema: JsonDict = field(default_factory=dict)
    annotations: JsonDict = field(default_factory=dict)
    source_urls: List[str] = field(default_factory=list)
    raw: JsonDict = field(default_factory=dict)
    write_confidence: str = "unknown"
    evidence: List[JsonDict] = field(default_factory=list)
    # Phase 2 capability layer: a plain "what it does" line and an example prompt
    # ("what to ask"), with the evidence tier the summary rests on.
    capability_summary: str = ""
    example_prompt: str = ""
    capability_tier: str = ""

    def to_dict(self) -> JsonDict:
        return {
            "provider": self.provider,
            "server_id": self.server_id,
            "name": self.name,
            "native_surface": self.native_surface,
            "description": self.description,
            "input_schema": self.input_schema,
            "annotations": self.annotations,
            "source_urls": sorted(set(self.source_urls)),
            "raw": self.raw,
            "write_confidence": self.write_confidence,
            "evidence": self.evidence,
            "capability_summary": self.capability_summary,
            "example_prompt": self.example_prompt,
            "capability_tier": self.capability_tier,
        }


@dataclass
class ServerRecord:
    provider: str
    server_id: str
    native_surface: str
    name: str
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    transport: str = "catalog"
    remote_url: str = ""
    tools: List[ToolRecord] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    write_confidence: str = "unknown"
    evidence: List[JsonDict] = field(default_factory=list)

    def to_dict(self, include_tools: bool = True) -> JsonDict:
        data: JsonDict = {
            "provider": self.provider,
            "server_id": self.server_id,
            "native_surface": self.native_surface,
            "name": self.name,
            "description": self.description,
            "capabilities": sorted(set(self.capabilities)),
            "source_urls": sorted(set(self.source_urls)),
            "transport": self.transport,
            "remote_url": self.remote_url,
            "metadata": self.metadata,
            "write_confidence": self.write_confidence,
            "evidence": self.evidence,
        }
        if include_tools:
            data["tools"] = [tool.to_dict() for tool in self.tools]
        return data


@dataclass
class CrawlIssue:
    provider: str
    source: str
    message: str
    severity: str = "warning"

    def to_dict(self) -> JsonDict:
        return {
            "provider": self.provider,
            "source": self.source,
            "severity": self.severity,
            "message": self.message,
        }

