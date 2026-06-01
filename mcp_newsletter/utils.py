from __future__ import annotations

import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .netguard import RetryPolicy, max_response_bytes, read_capped, should_retry


USER_AGENT = "mcp-newsletter/0.1 (+https://github.com/)"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        data = data.strip()
        if data:
            self.parts.append(data)


def today_iso() -> str:
    return dt.date.today().isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(data: Any) -> str:
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def safe_name(value: str) -> str:
    return slugify(value)[:120]


def html_to_text(markup: str) -> str:
    markup = re.sub(r"<script\b[^>]*>.*?</script>", " ", markup, flags=re.I | re.S)
    markup = re.sub(r"<style\b[^>]*>.*?</style>", " ", markup, flags=re.I | re.S)
    markup = re.sub(r"<svg\b[^>]*>.*?</svg>", " ", markup, flags=re.I | re.S)
    parser = _TextExtractor()
    parser.feed(markup)
    text = " ".join(parser.parts)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title(markup: str, fallback: str = "") -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", markup, flags=re.I | re.S)
    if match:
        return html_to_text(match.group(1)).strip()
    match = re.search(r"<h1[^>]*>(.*?)</h1>", markup, flags=re.I | re.S)
    if match:
        return html_to_text(match.group(1)).strip()
    return fallback


def extract_links(markup: str, base_url: str) -> List[str]:
    links: List[str] = []
    for match in re.finditer(r"""href=["']([^"']+)["']""", markup, flags=re.I):
        href = html.unescape(match.group(1))
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        links.append(urljoin(base_url, href))
    return sorted(set(links))


def extract_github_repos(markup: str) -> List[str]:
    repos = set()
    pattern = r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
    for owner, repo in re.findall(pattern, markup):
        repo = repo.removesuffix(".git")
        if repo.lower() in {"topics", "marketplace", "features"}:
            continue
        repos.add(f"https://github.com/{owner}/{repo}")
    return sorted(repos)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


_FETCH_RETRY = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=8.0)


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)  # delta-seconds form; HTTP-date form is ignored
    except (TypeError, ValueError):
        return None


def fetch_text(
    url: str,
    timeout: int = 20,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"}
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, headers=headers)
    attempt = 0
    while True:
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = read_capped(resp, max_response_bytes())
                charset = resp.headers.get_content_charset() or "utf-8"
                return body.decode(charset, "replace"), {
                    "url": url,
                    "status": getattr(resp, "status", None),
                    "content_type": resp.headers.get("content-type", ""),
                    "error": "",
                }
        except HTTPError as exc:
            retry_after = _parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            retry, delay = should_retry(_FETCH_RETRY, attempt, exc.code, retry_after)
            if retry:
                _sleep(delay)
                attempt += 1
                continue
            body = exc.read(4000).decode("utf-8", "replace") if exc.fp else ""
            return body, {"url": url, "status": exc.code, "content_type": "", "error": str(exc)}
        except ValueError as exc:
            # size-cap breach from read_capped is deterministic; retrying just
            # re-downloads the same oversized body, so fail fast.
            return None, {"url": url, "status": None, "content_type": "", "error": str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            retry, delay = should_retry(_FETCH_RETRY, attempt, None, None)
            if retry:
                _sleep(delay)
                attempt += 1
                continue
            return None, {"url": url, "status": None, "content_type": "", "error": str(exc)}


def unique_dicts(items: Iterable[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        value = item.get(key)
        if value in seen:
            continue
        seen.add(value)
        out.append(item)
    return out


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, child in value.items():
            if re.search(r"(token|secret|password|key|auth|credential)", key, flags=re.I):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_secrets(child)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
