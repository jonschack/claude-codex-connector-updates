from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional

from .context import CollectContext

# Phase 2 "signals" tier: ingest capability ANNOUNCEMENTS (vendor blogs / MCP
# changelog) — the narrative layer the catalog/registry tiers never had. A
# generic Atom+RSS parser keeps it source-agnostic; feeds are env-overridable.

# Verified working feeds (June 2026); override via MCP_NEWSLETTER_SIGNAL_FEEDS
# ("name=url,name=url"). Anthropic publishes no native feed, so a community
# mirror tracks its /news page. Re-verify periodically via the live-contract suite.
DEFAULT_FEEDS: Dict[str, str] = {
    "mcp_blog": "https://blog.modelcontextprotocol.io/index.xml",
    "openai_news": "https://openai.com/news/rss.xml",
    "anthropic_news": "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
    "simonwillison": "https://simonwillison.net/atom/everything/",
    "latent_space": "https://www.latent.space/feed",
    "github_changelog": "https://github.blog/changelog/feed/",  # vendor changelog (P4)
}

# HN Algolia: free, keyword-queryable, surfaces Show HN / launch threads the RSS
# feeds miss. JSON (not RSS), so it has its own parser + fetch (P4 recall).
HN_ALGOLIA_URL = ("https://hn.algolia.com/api/v1/search_by_date"
                  "?query=MCP%20server&tags=story&hitsPerPage=50")


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


def parse_hn_algolia(json_text: str, source: str = "hackernews") -> List[SignalRecord]:
    """Parse HN Algolia `hits` into SignalRecords (story URL, or the HN item page
    for text posts)."""
    try:
        data = json.loads(json_text or "")
    except (json.JSONDecodeError, TypeError):
        return []
    out: List[SignalRecord] = []
    for hit in (data.get("hits") if isinstance(data, dict) else None) or []:
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        url = hit.get("url") or ""
        if not url and hit.get("objectID"):
            url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        out.append(SignalRecord(
            source=source, title=title, url=url,
            published=hit.get("created_at", ""),
            summary=(hit.get("story_text") or "")[:500],
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

    # HN Algolia (JSON, not RSS) — only on the default feed set (env override
    # replaces the whole set and is assumed self-contained).
    if feeds is DEFAULT_FEEDS:
        body = ctx.fetch("signals", HN_ALGOLIA_URL, "feed-hackernews")
        if body:
            out.extend(parse_hn_algolia(body))
    return out
