from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from .models import ServerRecord, ToolRecord


RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
REPORTABLE = {"medium", "high"}

WRITE_TERMS = {
    "add",
    "archive",
    "assign",
    "cancel",
    "comment",
    "commit",
    "create",
    "delete",
    "deploy",
    "edit",
    "insert",
    "invite",
    "label",
    "merge",
    "move",
    "post",
    "publish",
    "remove",
    "reply",
    "schedule",
    "send",
    "set",
    "submit",
    "update",
    "upload",
    "write",
}

READ_TERMS = {
    "fetch",
    "find",
    "get",
    "list",
    "read",
    "retrieve",
    "search",
    "summarize",
}

WRITE_RE = re.compile(r"\b(" + "|".join(sorted(WRITE_TERMS)) + r")\b", flags=re.I)
READ_RE = re.compile(r"\b(" + "|".join(sorted(READ_TERMS)) + r")\b", flags=re.I)


# --- evidence tiers (the one canonical ranking, shared by all tiers) -----------
# Quality ordering of write evidence, strongest last. The frontier ranker (P3)
# imports this so the "declared_manifest ranks between claimed and annotation"
# rule lives in exactly one place.
EVIDENCE_TIER_RANK = {
    "none": 0,
    "claimed_description": 1,
    "declared_manifest": 2,
    "annotation": 3,
    "verified_tools": 4,
}

# Map each evidence `kind` (see _evidence below) to its tier. Anything from a live
# probe of the actual tool list (tool_text / tool_rollup) is `verified_tools`;
# MCP annotation hints are their own `annotation` tier; static manifest parses are
# `declared_manifest`; catalog/description heuristics are merely `claimed`.
_KIND_TO_TIER = {
    "tool_text": "verified_tools",
    "tool_rollup": "verified_tools",
    "mcp_annotation": "annotation",
    "declared_manifest": "declared_manifest",
    "catalog_capability": "claimed_description",
    "catalog_description": "claimed_description",
    "registry_description": "claimed_description",
}


def evidence_tier(evidence: Iterable[Dict[str, Any]]) -> str:
    """Strongest evidence tier present in `evidence`. Fail-closed: an unknown
    `kind` contributes `none` (it must be added to `_KIND_TO_TIER` to count), so a
    typo'd or future kind can never silently grant a record a write tier."""
    best = "none"
    for item in evidence or []:
        tier = _KIND_TO_TIER.get(item.get("kind"), "none")
        if EVIDENCE_TIER_RANK[tier] > EVIDENCE_TIER_RANK[best]:
            best = tier
    return best


def evidence_tiers(evidence: Iterable[Dict[str, Any]]) -> set:
    """Distinct (non-`none`) evidence tiers present — corroboration is how many
    independent tiers attest the write capability."""
    tiers = set()
    for item in evidence or []:
        tier = _KIND_TO_TIER.get(item.get("kind"), "none")
        if tier != "none":
            tiers.add(tier)
    return tiers


def reportable(confidence: str) -> bool:
    return confidence in REPORTABLE


def max_confidence(values: Iterable[str]) -> str:
    best = "unknown"
    for value in values:
        if RANK.get(value, 0) > RANK.get(best, 0):
            best = value
    return best


def _evidence(kind: str, value: Any, confidence: str) -> Dict[str, Any]:
    return {"kind": kind, "value": value, "confidence": confidence}


def classify_catalog(capabilities: List[str], description: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    evidence: List[Dict[str, Any]] = []
    joined_caps = " ".join(capabilities).lower()
    lowered_description = description.lower()
    if "read & write" in joined_caps or "read and write" in joined_caps or "write" in joined_caps:
        evidence.append(_evidence("catalog_capability", capabilities, "high"))
        return "high", evidence
    if "read & write" in lowered_description or "read and write" in lowered_description:
        evidence.append(_evidence("catalog_description", "read and write phrase", "high"))
        return "high", evidence
    if re.search(r"\b(manage|take action|take actions|modify|mutate)\b", lowered_description):
        evidence.append(_evidence("catalog_description", "action-oriented description", "medium"))
        return "medium", evidence
    if "read" in joined_caps:
        evidence.append(_evidence("catalog_capability", capabilities, "low"))
        return "low", evidence
    return "unknown", evidence


def classify_tool(tool: ToolRecord) -> Tuple[str, List[Dict[str, Any]]]:
    evidence: List[Dict[str, Any]] = []
    annotations = tool.annotations or {}
    if annotations.get("destructiveHint") is True:
        evidence.append(_evidence("mcp_annotation", "destructiveHint=true", "high"))
    if annotations.get("readOnlyHint") is True:
        evidence.append(_evidence("mcp_annotation", "readOnlyHint=true", "low"))
        if not any(item["confidence"] == "high" for item in evidence):
            return "low", evidence
    if annotations.get("readOnlyHint") is False:
        evidence.append(_evidence("mcp_annotation", "readOnlyHint=false", "medium"))

    schema_text = str(tool.input_schema or {})
    text = f"{tool.name} {tool.description} {schema_text}"
    write_match = WRITE_RE.search(text)
    read_match = READ_RE.search(text)
    if write_match:
        confidence = "high" if annotations.get("readOnlyHint") is False or annotations.get("destructiveHint") else "medium"
        evidence.append(_evidence("tool_text", write_match.group(0).lower(), confidence))
    elif read_match:
        evidence.append(_evidence("tool_text", read_match.group(0).lower(), "low"))

    if any(item["confidence"] == "high" for item in evidence):
        return "high", evidence
    if any(item["confidence"] == "medium" for item in evidence):
        return "medium", evidence
    if any(item["confidence"] == "low" for item in evidence):
        return "low", evidence
    return "unknown", evidence


def classify_server(server: ServerRecord) -> Tuple[str, List[Dict[str, Any]]]:
    catalog_confidence, evidence = classify_catalog(server.capabilities, server.description)
    tool_confidences = []
    for tool in server.tools:
        tool.write_confidence, tool.evidence = classify_tool(tool)
        tool_confidences.append(tool.write_confidence)
    confidence = max_confidence([catalog_confidence] + tool_confidences)
    if confidence in {"medium", "high"} and not evidence:
        evidence.append(_evidence("tool_rollup", "one or more tools appear write-capable", confidence))
    return confidence, evidence


def classify_all(servers: List[ServerRecord]) -> None:
    for server in servers:
        server.write_confidence, server.evidence = classify_server(server)

