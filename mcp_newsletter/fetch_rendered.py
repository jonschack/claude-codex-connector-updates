from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional, Tuple

from .netguard import max_response_bytes, read_capped
from .utils import USER_AGENT


FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"

Meta = Dict[str, Any]
Backend = Callable[..., Tuple[Optional[str], Meta]]


def _meta(url: str, status: Optional[int] = None, error: str = "", content_type: str = "") -> Meta:
    return {"url": url, "status": status, "content_type": content_type, "error": error}


def _firecrawl_backend(url: str, *, timeout: int = 60, **_: Any) -> Tuple[Optional[str], Meta]:
    """Render via Firecrawl /scrape and return main-content markdown.

    Hosted (no local browser); needs FIRECRAWL_API_KEY. Returns markdown that is
    already main-content extracted, solving rendering AND boilerplate at once.
    """
    from urllib.request import Request, urlopen

    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return None, _meta(url, error="FIRECRAWL_API_KEY not set")
    payload = json.dumps({"url": url, "formats": ["markdown"]}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    req = Request(FIRECRAWL_URL, data=payload, headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        body = read_capped(resp, max_response_bytes())
        data = json.loads(body.decode("utf-8", "replace"))
    markdown = (data.get("data") or {}).get("markdown")
    if markdown:
        return markdown, _meta(url, status=200, content_type="text/markdown")
    return None, _meta(url, error="firecrawl returned no markdown")


def _playwright_backend(url: str, *, timeout: int = 60000, wait_for: Optional[str] = None, **_: Any) -> Tuple[Optional[str], Meta]:
    """Render via a local headless Chromium (self-hosted fallback)."""
    from playwright.sync_api import sync_playwright  # lazy: optional dependency

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=timeout, wait_until="networkidle")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            html = page.content()
        finally:
            browser.close()
    return html, _meta(url, status=200, content_type="text/html")


_BACKENDS: Dict[str, Backend] = {
    "firecrawl": _firecrawl_backend,
    "playwright": _playwright_backend,
}


def fetch_rendered(
    url: str,
    *,
    backend: Optional[str] = None,
    _backend: Optional[Backend] = None,
    **kwargs: Any,
) -> Tuple[Optional[str], Meta]:
    """JS-rendering fetch, parallel to utils.fetch_text.

    Default backend is "none" (a deliberate no-op so the daily run is unchanged
    until rendering is explicitly enabled via MCP_NEWSLETTER_RENDER_BACKEND).
    `_backend` injects a callable for tests. Always returns (text|None, meta)
    with the standard meta keys; backend exceptions are captured into meta.error.
    """
    backend = backend or os.environ.get("MCP_NEWSLETTER_RENDER_BACKEND", "none")
    if _backend is not None:
        fn: Optional[Backend] = _backend
    elif backend == "none":
        return None, _meta(
            url,
            error="rendering disabled (set MCP_NEWSLETTER_RENDER_BACKEND=firecrawl|playwright)",
        )
    else:
        fn = _BACKENDS.get(backend)
        if fn is None:
            return None, _meta(url, error=f"unknown render backend: {backend}")
    try:
        text, meta = fn(url, **kwargs)
    except Exception as exc:  # network/library/credential failure -> captured, never raised
        return None, _meta(url, error=f"{type(exc).__name__}: {exc}")
    return text, _meta(
        url,
        status=meta.get("status"),
        error=meta.get("error", ""),
        content_type=meta.get("content_type", ""),
    )
