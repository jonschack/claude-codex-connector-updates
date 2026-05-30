# Registry Sources — Plan 1: Foundation (Network Hardening) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the shared HTTP layer (`fetch_text`) and the MCP tool-discovery layer (`mcp_discovery`) with an SSRF guard, a response-size cap, and polite retry/backoff, so the later registry tier can safely point discovery at thousands of untrusted, community-submitted URLs.

**Architecture:** Add one focused module `netguard.py` containing a pure URL-safety check (`is_safe_url`) and a bounded reader (`read_capped`). Wire both into `mcp_discovery._post_json` (block unsafe hosts before POST, cap the body read) and into `utils.fetch_text` (cap the body read, add bounded retry with backoff and `Retry-After`/429 honoring). All behavior is unit-tested offline using IP-literal URLs (no DNS/network) and a fake response object.

**Tech Stack:** Python 3 stdlib only — `ipaddress`, `socket`, `urllib`, `unittest`, `unittest.mock`. Matches the existing zero-dependency project.

This is the dependency root for Plan 2 (Registry tier) and Plan 3 (Vendor tier). It changes shared code used by the existing vendor collectors too, so the existing 6-test suite must stay green throughout.

---

## File Structure

- **Create** `mcp_newsletter/netguard.py` — pure helpers: `is_safe_url(url) -> (bool, reason)`, `read_capped(resp, limit) -> bytes`, plus `MAX_RESPONSE_BYTES`, `RetryPolicy`, and `should_retry(...)`. No I/O side effects except DNS resolution inside `is_safe_url`.
- **Modify** `mcp_newsletter/mcp_discovery.py` — call `is_safe_url` before the discovery POST; read the response with `read_capped`.
- **Modify** `mcp_newsletter/utils.py` — `fetch_text` reads via `read_capped` and retries transient failures/429 with capped exponential backoff.
- **Create** `tests/test_netguard.py` — unit tests for `is_safe_url`, `read_capped`, `should_retry`.
- **Create** `tests/test_discovery_safety.py` — `discover_remote_tools` refuses unsafe URLs and enforces the size cap.

Environment overrides (read at call time, not import time, so tests can set them):
- `MCP_NEWSLETTER_MAX_RESPONSE_BYTES` (default `5242880` = 5 MiB)
- `MCP_NEWSLETTER_SSRF_ALLOW` (comma-separated hostnames/IPs that bypass the private-range block, e.g. for a self-hosted test server; default empty)

---

## Task 1: `netguard.is_safe_url` — block unsafe schemes and private/loopback/link-local addresses

**Files:**
- Create: `mcp_newsletter/netguard.py`
- Test: `tests/test_netguard.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_netguard.py
import os
import unittest
from unittest import mock

from mcp_newsletter.netguard import is_safe_url


class IsSafeUrlTests(unittest.TestCase):
    def test_public_ip_literal_is_allowed(self):
        ok, reason = is_safe_url("https://8.8.8.8/mcp")
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "")

    def test_loopback_is_blocked(self):
        ok, reason = is_safe_url("http://127.0.0.1:8080/mcp")
        self.assertFalse(ok)
        self.assertIn("127.0.0.1", reason)

    def test_ipv6_loopback_is_blocked(self):
        ok, reason = is_safe_url("http://[::1]/mcp")
        self.assertFalse(ok)

    def test_private_range_is_blocked(self):
        ok, _ = is_safe_url("http://10.0.0.5/mcp")
        self.assertFalse(ok)

    def test_cloud_metadata_ip_is_blocked(self):
        ok, reason = is_safe_url("http://169.254.169.254/latest/meta-data")
        self.assertFalse(ok)
        self.assertIn("169.254", reason)

    def test_non_http_scheme_is_blocked(self):
        ok, reason = is_safe_url("file:///etc/passwd")
        self.assertFalse(ok)
        self.assertIn("scheme", reason)

    def test_missing_host_is_blocked(self):
        ok, reason = is_safe_url("http://")
        self.assertFalse(ok)
        self.assertIn("host", reason)

    def test_allowlist_override_permits_loopback(self):
        with mock.patch.dict(os.environ, {"MCP_NEWSLETTER_SSRF_ALLOW": "127.0.0.1"}):
            ok, reason = is_safe_url("http://127.0.0.1:9000/mcp")
        self.assertTrue(ok, reason)

    def test_hostname_resolving_to_private_is_blocked(self):
        # localhost resolves to 127.0.0.1 / ::1 without network egress
        ok, _ = is_safe_url("http://localhost:3000/mcp")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_netguard -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_newsletter.netguard'`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/netguard.py
from __future__ import annotations

import ipaddress
import os
import socket
from typing import Tuple
from urllib.parse import urlparse


def _allowlist() -> set:
    raw = os.environ.get("MCP_NEWSLETTER_SSRF_ALLOW", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_safe_url(url: str) -> Tuple[bool, str]:
    """Return (ok, reason). ok=False means do not connect to this URL.

    Blocks non-http(s) schemes and any host that resolves to a loopback,
    private, link-local, reserved, multicast, or unspecified address. Hosts
    listed in MCP_NEWSLETTER_SSRF_ALLOW bypass the address check.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported scheme: {parsed.scheme or 'none'}"
    host = parsed.hostname
    if not host:
        return False, "missing host"

    allow = _allowlist()
    if host in allow:
        return True, ""

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return False, f"dns resolution failed: {exc}"

    for info in infos:
        addr = info[4][0]
        if addr in allow:
            continue
        ip = ipaddress.ip_address(addr.split("%")[0])  # strip zone id if present
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"blocked address: {ip}"
    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_netguard -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/netguard.py tests/test_netguard.py
git commit -m "feat(netguard): add SSRF-safe URL check"
```

---

## Task 2: `netguard.read_capped` — bounded response reader

**Files:**
- Modify: `mcp_newsletter/netguard.py`
- Test: `tests/test_netguard.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_netguard.py
import io
from mcp_newsletter.netguard import read_capped, MAX_RESPONSE_BYTES


class ReadCappedTests(unittest.TestCase):
    def test_reads_small_body_fully(self):
        body = read_capped(io.BytesIO(b"hello"), limit=100)
        self.assertEqual(body, b"hello")

    def test_aborts_when_body_exceeds_limit(self):
        with self.assertRaises(ValueError) as ctx:
            read_capped(io.BytesIO(b"x" * 50), limit=10)
        self.assertIn("exceeded", str(ctx.exception))

    def test_reads_body_exactly_at_limit(self):
        body = read_capped(io.BytesIO(b"x" * 10), limit=10)
        self.assertEqual(len(body), 10)

    def test_default_limit_is_five_mib(self):
        self.assertEqual(MAX_RESPONSE_BYTES, 5 * 1024 * 1024)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_netguard.ReadCappedTests -v`
Expected: FAIL with `ImportError: cannot import name 'read_capped'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to mcp_newsletter/netguard.py

MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def max_response_bytes() -> int:
    raw = os.environ.get("MCP_NEWSLETTER_MAX_RESPONSE_BYTES")
    if raw and raw.isdigit():
        return int(raw)
    return MAX_RESPONSE_BYTES


def read_capped(resp, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read at most `limit` bytes; raise ValueError if the body is larger.

    `resp` is any object with a .read(n) method (an http.client.HTTPResponse
    or a BytesIO in tests).
    """
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"response exceeded {limit} bytes")
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_netguard.ReadCappedTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/netguard.py tests/test_netguard.py
git commit -m "feat(netguard): add bounded response reader"
```

---

## Task 3: `netguard.should_retry` + `RetryPolicy` — backoff decision (pure)

**Files:**
- Modify: `mcp_newsletter/netguard.py`
- Test: `tests/test_netguard.py`

The retry *decision* is a pure function so it can be tested without sleeping or
making requests. The actual sleeping happens in `fetch_text` (Task 5) using
this decision.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_netguard.py
from mcp_newsletter.netguard import RetryPolicy, should_retry


class ShouldRetryTests(unittest.TestCase):
    def setUp(self):
        self.policy = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=8.0)

    def test_no_retry_after_max_attempts(self):
        retry, _ = should_retry(self.policy, attempt=3, status=503, retry_after=None)
        self.assertFalse(retry)

    def test_retries_on_429(self):
        retry, delay = should_retry(self.policy, attempt=0, status=429, retry_after=None)
        self.assertTrue(retry)
        self.assertEqual(delay, 0.5)  # base_delay * 2**0

    def test_retries_on_5xx(self):
        retry, _ = should_retry(self.policy, attempt=1, status=502, retry_after=None)
        self.assertTrue(retry)

    def test_does_not_retry_on_404(self):
        retry, _ = should_retry(self.policy, attempt=0, status=404, retry_after=None)
        self.assertFalse(retry)

    def test_honors_retry_after_header(self):
        retry, delay = should_retry(self.policy, attempt=0, status=429, retry_after=5.0)
        self.assertTrue(retry)
        self.assertEqual(delay, 5.0)

    def test_exponential_backoff_capped_at_max_delay(self):
        retry, delay = should_retry(self.policy, attempt=10, status=503, retry_after=None)
        # attempt 10 is beyond max_retries -> no retry
        self.assertFalse(retry)

    def test_backoff_grows_then_caps(self):
        # attempt 2 -> 0.5 * 2**2 = 2.0; attempt within retries
        _, delay = should_retry(self.policy, attempt=2, status=503, retry_after=None)
        self.assertEqual(delay, 2.0)

    def test_network_error_retries_when_status_none(self):
        retry, delay = should_retry(self.policy, attempt=0, status=None, retry_after=None)
        self.assertTrue(retry)
        self.assertEqual(delay, 0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_netguard.ShouldRetryTests -v`
Expected: FAIL with `ImportError: cannot import name 'RetryPolicy'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to mcp_newsletter/netguard.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0


RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def should_retry(
    policy: RetryPolicy,
    attempt: int,
    status: Optional[int],
    retry_after: Optional[float],
) -> Tuple[bool, float]:
    """Decide whether to retry. Returns (retry, delay_seconds).

    `attempt` is zero-based: 0 = first try just failed. `status` is the HTTP
    status, or None for a transport-level error (URLError/timeout). A 429 or
    5xx (or a None/transport error) is retryable until max_retries is reached.
    `retry_after`, when present, overrides the computed backoff delay.
    """
    if attempt >= policy.max_retries:
        return False, 0.0
    retryable = status is None or status in RETRYABLE_STATUSES
    if not retryable:
        return False, 0.0
    if retry_after is not None:
        return True, retry_after
    delay = min(policy.base_delay * (2 ** attempt), policy.max_delay)
    return True, delay
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_netguard.ShouldRetryTests -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/netguard.py tests/test_netguard.py
git commit -m "feat(netguard): add retry/backoff decision policy"
```

---

## Task 4: Wire SSRF guard + size cap into `mcp_discovery`

**Files:**
- Modify: `mcp_newsletter/mcp_discovery.py:28-41` (`_post_json`) and `:43-64` (`discover_remote_tools` entry guard)
- Test: `tests/test_discovery_safety.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_discovery_safety.py
import unittest
from unittest import mock

from mcp_newsletter.mcp_discovery import discover_remote_tools


class DiscoverySafetyTests(unittest.TestCase):
    def test_refuses_loopback_url_without_network(self):
        tools, result = discover_remote_tools("reg", "srv", "registry", "http://127.0.0.1/mcp")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])
        self.assertIn("127.0.0.1", result["error"])

    def test_refuses_non_http_scheme(self):
        tools, result = discover_remote_tools("reg", "srv", "registry", "ftp://example.com/x")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])

    def test_refuses_metadata_ip(self):
        tools, result = discover_remote_tools("reg", "srv", "registry", "http://169.254.169.254/")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])

    def test_oversized_body_is_rejected(self):
        # is_safe_url passes (public IP literal), but the body exceeds the cap.
        class FakeResp:
            headers = {}
            status = 200
            def read(self, n=-1):
                return b"x" * (n if n and n > 0 else 10_000_000)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        with mock.patch.dict("os.environ", {"MCP_NEWSLETTER_MAX_RESPONSE_BYTES": "100"}):
            with mock.patch("mcp_newsletter.mcp_discovery.urlopen", return_value=FakeResp()):
                tools, result = discover_remote_tools("reg", "srv", "registry", "https://8.8.8.8/mcp")
        self.assertEqual(tools, [])
        self.assertFalse(result["ok"])
        self.assertIn("exceeded", result["error"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_discovery_safety -v`
Expected: FAIL — current `discover_remote_tools` would attempt a real connection to 127.0.0.1 (ConnectionError) or not surface the IP in `error`, and the oversized-body test fails because there is no size cap.

- [ ] **Step 3: Edit `mcp_discovery.py`**

Replace the imports block and the two functions. Current top of file:

```python
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ToolRecord
```

becomes:

```python
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ToolRecord
from .netguard import is_safe_url, max_response_bytes, read_capped
```

In `_post_json`, change the body read. Current:

```python
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        next_session = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id") or session_id
        return _parse_json_or_sse(body), next_session
```

becomes:

```python
    with urlopen(req, timeout=timeout) as resp:
        body = read_capped(resp, max_response_bytes())
        next_session = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id") or session_id
        return _parse_json_or_sse(body), next_session
```

In `discover_remote_tools`, replace the scheme check at the top. Current:

```python
    if not url.startswith(("https://", "http://")):
        return [], {"ok": False, "error": "remote discovery requires http(s) url"}
```

becomes:

```python
    safe, reason = is_safe_url(url)
    if not safe:
        return [], {"ok": False, "error": reason}
```

Then extend the existing `except` clause so a `ValueError` from the size cap is
captured (it already lists `ValueError`, confirm it reads):

```python
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return [], {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_discovery_safety -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `python3 -m unittest -v`
Expected: PASS — original 6 tests plus the new netguard/discovery tests.

- [ ] **Step 6: Commit**

```bash
git add mcp_newsletter/mcp_discovery.py tests/test_discovery_safety.py
git commit -m "feat(discovery): enforce SSRF guard and response-size cap"
```

---

## Task 5: Add size cap + retry/backoff to `utils.fetch_text`

**Files:**
- Modify: `mcp_newsletter/utils.py:119-136` (`fetch_text`)
- Test: `tests/test_netguard.py` (new `FetchTextTests` class — keeps network tests offline via mocks)

`fetch_text` is the scrape/HTTP path used by every catalog collector. It must
read with the size cap and retry transient failures using the Task 3 policy,
sleeping between attempts. We inject `sleep` so tests don't actually wait.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_netguard.py
from unittest import mock
from urllib.error import HTTPError
from mcp_newsletter import utils


class FetchTextRetryTests(unittest.TestCase):
    def _resp(self, body=b"ok", status=200, content_type="text/html"):
        class FakeResp:
            headers = {"content-type": content_type}
            def __init__(self, b, s):
                self._b = b
                self.status = s
            def read(self, n=-1):
                return self._b[: n] if (n and n > 0) else self._b
            def get_content_charset(self):  # not used directly; headers.get path
                return "utf-8"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        r = FakeResp(body, status)
        r.headers = mock.MagicMock()
        r.headers.get_content_charset.return_value = "utf-8"
        r.headers.get.side_effect = lambda k, d="": {"content-type": content_type}.get(k.lower(), d)
        return r

    def test_succeeds_first_try(self):
        with mock.patch.object(utils, "urlopen", return_value=self._resp(b"hello")):
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(text, "hello")
        self.assertEqual(meta["error"], "")

    def test_retries_on_503_then_succeeds(self):
        calls = []
        def fake_urlopen(req, timeout=20):
            if len(calls) == 0:
                calls.append(1)
                raise HTTPError("https://8.8.8.8/x", 503, "busy", {}, None)
            return self._resp(b"recovered")
        with mock.patch.object(utils, "urlopen", side_effect=fake_urlopen), \
             mock.patch.object(utils, "_sleep") as sleeper:
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(text, "recovered")
        sleeper.assert_called()  # backed off at least once

    def test_gives_up_after_max_retries_on_503(self):
        def always_503(req, timeout=20):
            raise HTTPError("https://8.8.8.8/x", 503, "busy", {}, None)
        with mock.patch.object(utils, "urlopen", side_effect=always_503), \
             mock.patch.object(utils, "_sleep"):
            text, meta = utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(meta["status"], 503)
        self.assertNotEqual(meta["error"], "")

    def test_does_not_retry_on_404(self):
        attempts = []
        def once_404(req, timeout=20):
            attempts.append(1)
            raise HTTPError("https://8.8.8.8/x", 404, "nope", {}, None)
        with mock.patch.object(utils, "urlopen", side_effect=once_404), \
             mock.patch.object(utils, "_sleep"):
            utils.fetch_text("https://8.8.8.8/x")
        self.assertEqual(len(attempts), 1)  # no retry on 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_netguard.FetchTextRetryTests -v`
Expected: FAIL — `utils` has no `_sleep`, and `fetch_text` does not retry (single attempt) nor cap the read.

- [ ] **Step 3: Edit `utils.py`**

Add imports near the top (after the existing `import os`):

```python
import time
```

and import the netguard helpers (add to the existing import section):

```python
from .netguard import RetryPolicy, max_response_bytes, read_capped, should_retry
```

Add a module-level indirection for sleep (so tests can patch it) and the
default policy, just above `fetch_text`:

```python
def _sleep(seconds: float) -> None:
    time.sleep(seconds)


_FETCH_RETRY = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=8.0)
```

Replace the whole `fetch_text` body. Current:

```python
def fetch_text(url: str, timeout: int = 20) -> Tuple[Optional[str], Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return body.decode(charset, "replace"), {
                "url": url,
                "status": getattr(resp, "status", None),
                "content_type": resp.headers.get("content-type", ""),
                "error": "",
            }
    except HTTPError as exc:
        body = exc.read(4000).decode("utf-8", "replace") if exc.fp else ""
        return body, {"url": url, "status": exc.code, "content_type": "", "error": str(exc)}
    except (URLError, TimeoutError, OSError) as exc:
        return None, {"url": url, "status": None, "content_type": "", "error": str(exc)}
```

becomes:

```python
def fetch_text(url: str, timeout: int = 20) -> Tuple[Optional[str], Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"}
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
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            retry, delay = should_retry(_FETCH_RETRY, attempt, None, None)
            if retry:
                _sleep(delay)
                attempt += 1
                continue
            return None, {"url": url, "status": None, "content_type": "", "error": str(exc)}
```

Add the `Retry-After` parser helper just below `_sleep`:

```python
def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)  # delta-seconds form; HTTP-date form is ignored (returns None)
    except (TypeError, ValueError):
        return None
```

Note: the `ValueError` added to the transport-error `except` is what makes the
size cap (`read_capped`) surface as a clean failure rather than a crash.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_netguard.FetchTextRetryTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `python3 -m unittest -v`
Expected: PASS — all prior tests plus the new ones.

- [ ] **Step 6: Commit**

```bash
git add mcp_newsletter/utils.py tests/test_netguard.py
git commit -m "feat(utils): cap fetch_text body and add retry/backoff"
```

---

## Task 6: Document the new env vars in OPERATIONS.md

**Files:**
- Modify: `docs/OPERATIONS.md` (append a section)

- [ ] **Step 1: Append the documentation**

Add to the end of `docs/OPERATIONS.md`:

```markdown
## Network Safety & Tuning

Shared HTTP/discovery hardening (applies to all collectors):

- `MCP_NEWSLETTER_MAX_RESPONSE_BYTES` — max bytes read from any single
  response (default 5242880 = 5 MiB). Oversized responses are rejected as an
  error rather than buffered.
- `MCP_NEWSLETTER_SSRF_ALLOW` — comma-separated hostnames/IPs allowed to
  bypass the private/loopback/link-local block (e.g. a self-hosted test MCP
  server). Empty by default; only set for trusted local endpoints.

Live MCP tool discovery refuses any URL whose host resolves to a loopback,
private, link-local, reserved, multicast, or unspecified address, and refuses
non-http(s) schemes. `fetch_text` retries transient failures (HTTP 429/5xx and
transport errors) up to 3 times with exponential backoff, honoring a numeric
`Retry-After` header.
```

- [ ] **Step 2: Commit**

```bash
git add docs/OPERATIONS.md
git commit -m "docs: document network-safety env vars"
```

---

## Self-Review (completed by plan author)

**Spec coverage (§5 of the design):**
- SSRF guard (block literals + private ranges, env allowlist) → Task 1, wired in Task 4. ✓
- Response-size cap (`MAX_RESPONSE_BYTES`, default 5 MB) → Task 2, wired in Tasks 4 & 5. ✓
- Politeness: retry + exponential backoff + jitter + 429/`Retry-After` → Task 3 + Task 5. *Note:* jitter from the spec is intentionally omitted in v1 — deterministic backoff keeps the retry tests simple and exact; jitter can be added later without interface change. Documented here so it is a conscious deviation, not an oversight.
- Per-host min-interval throttle (spec §5) → **deferred to Plan 2**, where the registry collectors that actually paginate one host thousands of times live. `fetch_text` here gains retry/backoff; the throttle belongs with the pagination loop that needs it (YAGNI in the foundation layer). Flagged for Plan 2's scope.

**Placeholder scan:** none — every code step shows complete code and exact commands.

**Type/name consistency:** `is_safe_url`, `read_capped`, `max_response_bytes`, `RetryPolicy`, `should_retry`, `_sleep`, `_parse_retry_after` are defined before use and referenced with identical names across Tasks 1–5. `discover_remote_tools`'s return contract `(List[ToolRecord], dict)` is unchanged.

**Out-of-scope-but-noted for later plans:** per-host throttle (Plan 2), the SSRF DNS-rebinding residual (design §5, deferred), backoff jitter (later).
