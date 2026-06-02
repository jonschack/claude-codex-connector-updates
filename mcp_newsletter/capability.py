from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from .models import ServerRecord, ToolRecord

# Phase 2 capability layer. Turns a tool into a plain "what it does" line and an
# example prompt ("what to ask"), tagged with the evidence tier the summary rests
# on. Default is deterministic (offline, no cost); an optional `llm` callable can
# produce richer prose, but the evidence tier is always derived from observed
# signal, never from the LLM (the project's "evidence, not trust" discipline).

Llm = Callable[[ToolRecord], Optional[Dict[str, str]]]

_WRITE_VERBS = {
    "create", "add", "update", "delete", "remove", "send", "post", "set", "write",
    "insert", "upsert", "publish", "schedule", "cancel", "move", "rename", "edit",
    "make", "provision", "deploy", "run", "execute", "start", "stop",
}


def humanize_tool_name(name: str) -> str:
    base = name.split(".")[-1]
    base = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base)  # camelCase -> camel_Case
    return re.sub(r"[_\-]+", " ", base).strip().lower()


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s", text, maxsplit=1)
    return parts[0].strip()


def evidence_tier(tool: ToolRecord) -> str:
    if tool.input_schema:
        return "verified_tools"
    if tool.annotations:
        return "annotation"
    if tool.description:
        return "claimed_description"
    return "none"


def _example_prompt(tool: ToolRecord, human: str) -> str:
    action = human or f"use {tool.name}"
    required = tool.input_schema.get("required") if isinstance(tool.input_schema, dict) else None
    if required:
        return f'"Claude, {action} (e.g. set {required[0]})"'
    return f'"Claude, {action}"'


def summarize_tool(tool: ToolRecord, llm: Optional[Llm] = None) -> Dict[str, str]:
    tier = evidence_tier(tool)
    human = humanize_tool_name(tool.name)
    summary = _first_sentence(tool.description) or (human.capitalize() if human else tool.name)
    example = _example_prompt(tool, human)
    if llm is not None:
        try:
            result = llm(tool)
        except Exception:
            result = None
        if result:
            summary = result.get("summary") or summary
            example = result.get("example_prompt") or example
    return {"summary": summary, "example_prompt": example, "evidence_tier": tier}


def enrich_servers(servers: List[ServerRecord], llm: Optional[Llm] = None) -> int:
    """Fill capability_summary / example_prompt / capability_tier on every tool.
    Returns the number of tools enriched."""
    count = 0
    for server in servers:
        for tool in server.tools:
            out = summarize_tool(tool, llm=llm)
            tool.capability_summary = out["summary"]
            tool.example_prompt = out["example_prompt"]
            tool.capability_tier = out["evidence_tier"]
            count += 1
    return count


def build_capability_feed(servers: List[ServerRecord]) -> List[Dict[str, object]]:
    """A flat 'what you can ask' feed across all tools, sorted deterministically
    by evidence tier (verified first) then provider/server/tool."""
    tier_rank = {"verified_tools": 0, "annotation": 1, "claimed_description": 2, "none": 3}
    feed: List[Dict[str, object]] = []
    for server in servers:
        for tool in server.tools:
            tier = tool.capability_tier or evidence_tier(tool)
            feed.append({
                "provider": server.provider,
                "server": server.name,
                "server_id": server.server_id,
                "tool": tool.name,
                "summary": tool.capability_summary or summarize_tool(tool)["summary"],
                "example_prompt": tool.example_prompt or summarize_tool(tool)["example_prompt"],
                "evidence_tier": tier,
                "write_confidence": tool.write_confidence,
                "source_urls": sorted(set(server.source_urls)),
            })
    feed.sort(key=lambda e: (tier_rank.get(e["evidence_tier"], 9), e["provider"], e["server"], e["tool"]))
    return feed
