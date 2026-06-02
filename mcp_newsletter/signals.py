from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional

from .context import CollectContext

# Phase 2 "signals" tier: ingest capability ANNOUNCEMENTS (vendor blogs / MCP
# changelog) — the narrative layer the catalog/registry tiers never had. A
# generic Atom+RSS parser keeps it source-agnostic; feeds are env-overridable.

# Best-effort default feeds; override via MCP_NEWSLETTER_SIGNAL_FEEDS
# ("name=url,name=url"). Live URLs are validated by the live-contract suite.
DEFAULT_FEEDS: Dict[str, str] = {
    "mcp_blog": "https://blog.modelcontextprotocol.io/atom.xml",
    "anthropic_news": "https://www.anthropic.com/rss.xml",
}


@dataclass
class SignalRecord:
    source: str
    title: str
    url: str = ""
    published: str = ""
    summary: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "published": self.published,
            "summary": self.summary,
        }


def _child_text(elem, name: str) -> str:
    found = elem.find(f"{{*}}{name}")
    if found is not None and found.text:
        return found.text.strip()
    return ""


def _atom_link(elem) -> str:
    link = elem.find("{*}link")
    if link is not None:
        return (link.get("href") or link.text or "").strip()
    return ""


def parse_feed(xml_text: str, source: str) -> List[SignalRecord]:
    """Parse Atom <entry> or RSS <item> elements into SignalRecords."""
    try:
        root = ET.fromstring((xml_text or "").strip())
    except ET.ParseError:
        return []
    out: List[SignalRecord] = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "entry":  # Atom
            title = _child_text(elem, "title")
            if not title:
                continue
            out.append(SignalRecord(
                source=source,
                title=title,
                url=_atom_link(elem),
                published=_child_text(elem, "updated") or _child_text(elem, "published"),
                summary=_child_text(elem, "summary") or _child_text(elem, "content"),
            ))
        elif tag == "item":  # RSS
            title = _child_text(elem, "title")
            if not title:
                continue
            out.append(SignalRecord(
                source=source,
                title=title,
                url=_child_text(elem, "link"),
                published=_child_text(elem, "pubDate"),
                summary=_child_text(elem, "description"),
            ))
    return out


def _feeds_from_env() -> Optional[Dict[str, str]]:
    raw = os.environ.get("MCP_NEWSLETTER_SIGNAL_FEEDS")
    if not raw:
        return None
    feeds: Dict[str, str] = {}
    for pair in raw.split(","):
        if "=" in pair:
            name, url = pair.split("=", 1)
            feeds[name.strip()] = url.strip()
    return feeds or None


def collect_signals(ctx: CollectContext, feeds: Optional[Dict[str, str]] = None) -> List[SignalRecord]:
    if ctx.skip_network:
        return []
    feeds = feeds or _feeds_from_env() or DEFAULT_FEEDS
    out: List[SignalRecord] = []
    for name, url in feeds.items():
        body = ctx.fetch("signals", url, f"feed-{name}")
        if not body:
            continue
        records = parse_feed(body, name)
        if not records:
            ctx.add_issue("signals", url, f"no entries parsed from feed '{name}'", severity="info")
        out.extend(records)
    return out
