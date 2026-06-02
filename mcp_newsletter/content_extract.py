from __future__ import annotations

import re
from typing import List

from .utils import html_to_text


# Page "chrome" that is never the connector's description. Stripped (tag +
# contents) before content selection so it cannot leak through the body
# fallback path (the root cause of nav-boilerplate descriptions).
_CHROME_TAGS = ("script", "style", "svg", "nav", "header", "footer", "aside")


def _strip_blocks(markup: str, tags) -> str:
    for tag in tags:
        markup = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", markup, flags=re.I | re.S)
    return markup


def _candidate_regions(markup: str) -> List[str]:
    """Candidate main-content regions, most-specific first: <main>, <article>,
    then <body> (or the whole doc)."""
    regions: List[str] = []
    for tag in ("main", "article"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", markup, flags=re.I | re.S)
        if match:
            regions.append(match.group(1))
    body = re.search(r"<body\b[^>]*>(.*?)</body>", markup, flags=re.I | re.S)
    regions.append(body.group(1) if body else markup)
    return regions


def extract_main_text(markup: str) -> str:
    """Return clean main-content text, dropping nav/header/footer/script chrome.

    Replaces whole-page `html_to_text`, which flattened navigation and footer
    boilerplate into connector descriptions. Falls through candidate regions so
    an empty <main> doesn't lose content that lives elsewhere in the body.
    """
    if not markup or not markup.strip():
        return ""
    cleaned = _strip_blocks(markup, _CHROME_TAGS)
    for region in _candidate_regions(cleaned):
        text = html_to_text(_strip_blocks(region, _CHROME_TAGS))
        if text.strip():
            return text
    return html_to_text(cleaned)
