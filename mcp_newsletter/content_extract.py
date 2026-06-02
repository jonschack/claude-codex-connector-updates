from __future__ import annotations

import re

from .utils import html_to_text


# Page "chrome" that is never the connector's description. Stripped (tag +
# contents) before content selection so it cannot leak through the body
# fallback path (the root cause of nav-boilerplate descriptions).
_CHROME_TAGS = ("script", "style", "svg", "nav", "header", "footer", "aside")


def _strip_blocks(markup: str, tags) -> str:
    for tag in tags:
        markup = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", markup, flags=re.I | re.S)
    return markup


def _region(markup: str) -> str:
    """Pick the main-content region: <main>, else <article>, else <body>."""
    for tag in ("main", "article"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", markup, flags=re.I | re.S)
        if match:
            return match.group(1)
    match = re.search(r"<body\b[^>]*>(.*?)</body>", markup, flags=re.I | re.S)
    return match.group(1) if match else markup


def extract_main_text(markup: str) -> str:
    """Return clean main-content text, dropping nav/header/footer/script chrome.

    Replaces whole-page `html_to_text`, which flattened navigation and footer
    boilerplate into connector descriptions.
    """
    if not markup or not markup.strip():
        return ""
    cleaned = _strip_blocks(markup, _CHROME_TAGS)
    region = _region(cleaned)
    # belt-and-suspenders: drop any chrome nested inside the selected region
    region = _strip_blocks(region, _CHROME_TAGS)
    return html_to_text(region)
