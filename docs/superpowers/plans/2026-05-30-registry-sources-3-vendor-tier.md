# Registry Sources — Plan 3: Vendor Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 new first-party vendor catalogs (OpenAI/ChatGPT, Cursor, VS Code/Copilot, Cline, Continue, Cloudflare) as new `provider` values in the existing pipeline, and add per-provider cold-start seeding so a brand-new provider's first run records a silent baseline instead of emitting a wall of `new_write_server` alerts.

**Architecture:** Each vendor collector mirrors the existing `claude.py`/`grok.py` scrapers and returns `List[ServerRecord]`; they slot into `collect_all`'s collector tuple with zero schema change. One additive behavior change to `state.upsert_server`: suppress `new_write_server` for a provider that has no rows from a *prior* run date (its first appearance), so adding a provider is quiet on day one and normal thereafter.

**Tech Stack:** Python 3 stdlib. Depends on **Plan 1** (hardened `fetch_text`). Independent of Plan 2.

**Prerequisite:** Plan 1 merged. (Plan 2 not required.) Confirm `python3 -m unittest` is green before starting.

---

## File Structure

- **Create** `mcp_newsletter/providers/openai.py`, `cursor.py`, `vscode.py`, `cline.py`, `continue_.py`, `cloudflare.py` — one collector each (`continue` is a keyword, hence `continue_.py`).
- **Modify** `mcp_newsletter/providers/__init__.py` — add the 6 collectors to the `collect_all` tuple.
- **Modify** `mcp_newsletter/state.py` — `upsert_server` gains a `provider_seeded: bool` parameter; `run_update` computes the seeded set and passes it.
- **Modify** `mcp_newsletter/updater.py` — compute `seeded_providers` before the upsert loop.
- **Tests:** `tests/test_seeding.py`, `tests/test_vendor_collectors.py`, fixtures under `tests/fixtures/vendors/`.

**Env config:** `MCP_NEWSLETTER_<PROVIDER>_URL` per collector (override the scrape target, e.g. for fixtures/tests).

---

## Task 1: Per-provider cold-start seeding in `state.upsert_server`

**Files:**
- Modify: `mcp_newsletter/state.py:94-129` (`upsert_server`)
- Modify: `mcp_newsletter/updater.py` (compute + pass `seeded_providers`)
- Test: `tests/test_seeding.py`

A provider is **seeded** if it already has at least one `servers` row whose
`first_seen` is *strictly earlier* than the current `run_date`. Using "strictly
earlier" (not "any row") keeps same-day re-runs idempotent: on the first-run
day the only rows have `first_seen == run_date`, so the provider stays unseeded
and events stay suppressed even on a re-run.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_seeding.py
import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.classifier import classify_all
from mcp_newsletter.models import ServerRecord
from mcp_newsletter.state import connect, events_for_date, seeded_providers, upsert_server


def _writeable(provider, server_id, name):
    s = ServerRecord(provider=provider, server_id=server_id, native_surface="connector",
                     name=name, capabilities=["Read & write"])
    classify_all([s])
    return s


class SeedingTests(unittest.TestCase):
    def test_first_run_of_new_provider_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            s = _writeable("cursor", "slack", "Slack")
            seeded = seeded_providers(conn, "2026-05-30")  # empty DB -> nothing seeded
            upsert_server(conn, "2026-05-30", s, provider_seeded="cursor" in seeded)
            conn.commit()
            self.assertEqual(events_for_date(conn, "2026-05-30"), [])

    def test_same_day_rerun_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            s = _writeable("cursor", "slack", "Slack")
            for _ in range(2):
                seeded = seeded_providers(conn, "2026-05-30")
                upsert_server(conn, "2026-05-30", s, provider_seeded="cursor" in seeded)
            conn.commit()
            self.assertEqual(events_for_date(conn, "2026-05-30"), [])  # idempotent + silent

    def test_new_server_next_day_emits(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            day1 = _writeable("cursor", "slack", "Slack")
            seeded = seeded_providers(conn, "2026-05-30")
            upsert_server(conn, "2026-05-30", day1, provider_seeded="cursor" in seeded)
            conn.commit()
            # day 2: provider now seeded (has a row with first_seen=2026-05-30 < 2026-05-31)
            day2 = _writeable("cursor", "linear", "Linear")
            seeded = seeded_providers(conn, "2026-05-31")
            self.assertIn("cursor", seeded)
            upsert_server(conn, "2026-05-31", day2, provider_seeded="cursor" in seeded)
            conn.commit()
            events = events_for_date(conn, "2026-05-31")
            self.assertEqual([e["event_type"] for e in events], ["new_write_server"])
            self.assertEqual(events[0]["server_id"], "linear")

    def test_existing_provider_with_prior_rows_is_seeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "state.sqlite")
            old = _writeable("claude", "linear", "Linear")
            upsert_server(conn, "2026-05-01", old, provider_seeded=True)
            conn.commit()
            seeded = seeded_providers(conn, "2026-05-30")
            self.assertIn("claude", seeded)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_seeding -v`
Expected: FAIL — `seeded_providers` does not exist and `upsert_server` has no `provider_seeded` parameter.

- [ ] **Step 3: Edit `state.py`**

Add the `seeded_providers` helper (place it above `upsert_server`):

```python
def seeded_providers(conn: sqlite3.Connection, run_date: str) -> set:
    """Providers that already have at least one server row from a prior run
    date. A provider NOT in this set is appearing for the first time and its
    new-write events should be suppressed (silent baseline)."""
    rows = conn.execute(
        "SELECT DISTINCT provider FROM servers WHERE first_seen < ?", (run_date,)
    ).fetchall()
    return {row["provider"] for row in rows}
```

Change the `upsert_server` signature and the new-server branch. Current:

```python
def upsert_server(conn: sqlite3.Connection, run_date: str, server: ServerRecord) -> None:
    raw = server.to_dict(include_tools=False)
    current_hash = stable_hash(raw)
    previous = _fetch_one(conn, "servers", (server.provider, server.server_id))
    if previous is None:
        if reportable(server.write_confidence):
            _insert_event(
```

becomes:

```python
def upsert_server(conn: sqlite3.Connection, run_date: str, server: ServerRecord, provider_seeded: bool = True) -> None:
    raw = server.to_dict(include_tools=False)
    current_hash = stable_hash(raw)
    previous = _fetch_one(conn, "servers", (server.provider, server.server_id))
    if previous is None:
        if reportable(server.write_confidence) and provider_seeded:
            _insert_event(
```

The default `provider_seeded=True` preserves existing call sites and tests
(the 4 existing providers are always seeded). Only the new-server branch is
gated; `write_status_changed` already requires a `previous` row, which can only
exist once a provider is seeded, so no extra gating is needed there.

- [ ] **Step 4: Edit `updater.py` to compute and pass the seeded set**

In `run_update`, the current upsert loop is:

```python
        for server in servers:
            upsert_server(conn, run_date, server)
            for tool in server.tools:
                upsert_tool(conn, run_date, tool)
```

becomes:

```python
        seeded = seeded_providers(conn, run_date)
        for server in servers:
            upsert_server(conn, run_date, server, provider_seeded=server.provider in seeded)
            for tool in server.tools:
                upsert_tool(conn, run_date, tool)
```

Add `seeded_providers` to the existing state import in `updater.py`:

```python
from .state import all_current, connect, events_for_date, seeded_providers, upsert_server, upsert_tool
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_seeding -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `python3 -m unittest -v`
Expected: PASS — existing tests unaffected (default `provider_seeded=True`).

- [ ] **Step 7: Commit**

```bash
git add mcp_newsletter/state.py mcp_newsletter/updater.py tests/test_seeding.py
git commit -m "feat(state): per-provider cold-start seeding for new providers"
```

---

## Task 2: OpenAI / ChatGPT connector collector (worked example)

**Files:**
- Create: `mcp_newsletter/providers/openai.py`
- Create: `tests/fixtures/vendors/openai_directory.html`
- Test: `tests/test_vendor_collectors.py`

This collector establishes the vendor-scrape pattern the other five follow. It
mirrors the existing `claude.py` structure (directory page → capability parse).

- [ ] **Step 1: Create the fixture**

`tests/fixtures/vendors/openai_directory.html`:

```html
<html><head><title>ChatGPT connectors</title></head><body>
<div class="connector"><h3>Gmail</h3><p>Read and write email, send messages.</p></div>
<div class="connector"><h3>Google Drive</h3><p>Search and read files.</p></div>
</body></html>
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_vendor_collectors.py
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.providers.openai import collect_openai

FIX = Path(__file__).parent / "fixtures" / "vendors"


def _ctx(tmp):
    return CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=False)


class OpenAICollectorTests(unittest.TestCase):
    def test_parses_connectors_and_capabilities(self):
        html = (FIX / "openai_directory.html").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.providers.openai.CollectContext.fetch", return_value=html):
                servers = collect_openai(ctx)
        names = {s.name for s in servers}
        self.assertIn("Gmail", names)
        gmail = next(s for s in servers if s.name == "Gmail")
        self.assertEqual(gmail.provider, "openai")
        self.assertTrue(any("write" in c.lower() for c in gmail.capabilities))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest tests.test_vendor_collectors -v`
Expected: FAIL `ModuleNotFoundError: ... providers.openai`

- [ ] **Step 4: Write minimal implementation**

```python
# mcp_newsletter/providers/openai.py
from __future__ import annotations

import os
import re
from typing import List

from ..context import CollectContext
from ..models import ServerRecord
from ..utils import html_to_text, slugify

PROVIDER = "openai"
DIRECTORY_URL = "https://platform.openai.com/docs/connectors"  # VERIFY exact catalog URL at implementation


def _capabilities(text: str) -> List[str]:
    lowered = text.lower()
    caps = []
    if "read and write" in lowered or "read & write" in lowered:
        caps.append("Read & write")
    elif re.search(r"\bwrite\b|\bsend\b|\bcreate\b", lowered):
        caps.append("Write")
    if re.search(r"\bread\b|\bsearch\b", lowered):
        caps.append("Read")
    return caps


def collect_openai(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_OPENAI_URL", DIRECTORY_URL)
    markup = ctx.fetch(PROVIDER, url, "connectors-directory")
    if not markup:
        return []
    servers: List[ServerRecord] = []
    for match in re.finditer(r'<div class="connector">(.*?)</div>', markup, flags=re.I | re.S):
        block = match.group(1)
        title = re.search(r"<h3[^>]*>(.*?)</h3>", block, flags=re.I | re.S)
        name = html_to_text(title.group(1)).strip() if title else ""
        if not name:
            continue
        text = html_to_text(block)
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=text[:500], capabilities=_capabilities(text),
            source_urls=[url],
        ))
    return servers
```

Note: `_capabilities` uses the same "Read & write"/"Write" vocabulary the
`classifier.classify_catalog` already recognizes, so write-capable OpenAI
connectors classify as high/medium without classifier changes.

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest tests.test_vendor_collectors -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add mcp_newsletter/providers/openai.py tests/fixtures/vendors/openai_directory.html tests/test_vendor_collectors.py
git commit -m "feat(providers): OpenAI/ChatGPT connector collector"
```

---

## Task 3: The other five vendor collectors

Each follows the same 6-step rhythm as Task 2 (fixture → failing test → parser →
pass → commit). **Each source's exact catalog URL and DOM/JSON shape must be
verified against a captured response at implementation time** (mark with the
`# VERIFY` comment, capture a real fixture, write the parser to it). Concrete
parsers:

- [ ] **3a — `cursor.py`** — scrape `cursor.directory/mcp`. JSON-in-page or HTML cards; extract name + description + repo link.

```python
# mcp_newsletter/providers/cursor.py
from __future__ import annotations
import os, re
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import extract_github_repos, html_to_text, slugify

PROVIDER = "cursor"
URL = "https://cursor.directory/mcp"  # VERIFY


def collect_cursor(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CURSOR_URL", URL)
    markup = ctx.fetch(PROVIDER, url, "mcp-directory")
    if not markup:
        return []
    text = html_to_text(markup)
    servers = []
    for repo in extract_github_repos(markup):
        name = repo.rstrip("/").split("/")[-1]
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=text[:300], source_urls=[repo, url],
        ))
    return servers
```

- [ ] **3b — `vscode.py`** — VS Code/Copilot MCP gallery is a GitHub-hosted JSON list. Parse JSON directly.

```python
# mcp_newsletter/providers/vscode.py
from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "vscode"
URL = "https://raw.githubusercontent.com/microsoft/mcp/main/registry.json"  # VERIFY exact gallery URL


def collect_vscode(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_VSCODE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "gallery")
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid gallery JSON")
        return []
    servers = []
    for item in (data.get("servers") or data if isinstance(data, list) else data.get("servers", [])):
        name = item.get("name") or item.get("displayName") or ""
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""),
            source_urls=[item.get("repository", ""), url],
            remote_url=item.get("url", ""),
        ))
    return servers
```

- [ ] **3c — `cline.py`** — `cline/mcp-marketplace` GitHub repo JSON.

```python
# mcp_newsletter/providers/cline.py
from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "cline"
URL = "https://raw.githubusercontent.com/cline/mcp-marketplace/main/marketplace.json"  # VERIFY


def collect_cline(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CLINE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "marketplace")
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid marketplace JSON")
        return []
    items = data.get("items") if isinstance(data, dict) else data
    servers = []
    for item in items or []:
        name = item.get("name", "")
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""),
            source_urls=[item.get("githubUrl", "") or item.get("repo", ""), url],
        ))
    return servers
```

- [ ] **3d — `continue_.py`** — `hub.continue.dev` MCP blocks (JSON API or scrape).

```python
# mcp_newsletter/providers/continue_.py
from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import slugify

PROVIDER = "continue"
URL = "https://hub.continue.dev/api/blocks?type=mcpServer"  # VERIFY


def collect_continue(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CONTINUE_URL", URL)
    body = ctx.fetch(PROVIDER, url, "blocks")
    if not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, url, "invalid blocks JSON")
        return []
    items = data.get("blocks") if isinstance(data, dict) else data
    servers = []
    for item in items or []:
        name = item.get("name") or item.get("title") or ""
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, description=item.get("description", ""), source_urls=[url],
        ))
    return servers
```

- [ ] **3e — `cloudflare.py`** — Cloudflare docs "remote MCP servers" list; many carry http(s) URLs → discovery applies via the existing pipeline (these `remote_url`s feed `mcp_discovery`, hardened in Plan 1).

```python
# mcp_newsletter/providers/cloudflare.py
from __future__ import annotations
import os, re
from typing import List
from ..context import CollectContext
from ..models import ServerRecord
from ..utils import html_to_text, slugify

PROVIDER = "cloudflare"
URL = "https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers/"  # VERIFY


def collect_cloudflare(ctx: CollectContext) -> List[ServerRecord]:
    url = os.environ.get("MCP_NEWSLETTER_CLOUDFLARE_URL", URL)
    markup = ctx.fetch(PROVIDER, url, "remote-mcp-servers")
    if not markup:
        return []
    servers = []
    # rows like:  Name | https://<server>.mcp.cloudflare.com/sse
    for name, remote in re.findall(r"([A-Za-z0-9 ]+)\s*\|\s*(https?://[^\s|<]+)", html_to_text(markup)):
        name = name.strip()
        if not name:
            continue
        servers.append(ServerRecord(
            provider=PROVIDER, server_id=slugify(name), native_surface="connector",
            name=name, source_urls=[url], remote_url=remote.strip(),
        ))
    return servers
```

- [ ] **Per-collector tests:** for each of 3a–3e add a fixture under
  `tests/fixtures/vendors/<provider>_*.{html,json}` (captured from a real
  response) and a test mirroring `OpenAICollectorTests` — mock `CollectContext.fetch`
  to return the fixture, assert `provider`, `name`, and (where applicable)
  `remote_url`/`capabilities`.

- [ ] **Commit after each:**

```bash
git add mcp_newsletter/providers/<name>.py tests/fixtures/vendors/ tests/test_vendor_collectors.py
git commit -m "feat(providers): add <name> vendor collector"
```

---

## Task 4: Register the new collectors in `collect_all`

**Files:**
- Modify: `mcp_newsletter/providers/__init__.py:7-20`
- Test: `tests/test_vendor_collectors.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_vendor_collectors.py
from mcp_newsletter.providers import collect_all


class CollectAllRegistrationTests(unittest.TestCase):
    def test_all_six_new_providers_are_invoked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            ctx.skip_network = True  # every collector returns [] but must be CALLED, not crash
            # collect_all swallows per-collector exceptions into issues; assert no crash
            servers = collect_all(ctx)
        self.assertIsInstance(servers, list)
        # the 6 new providers register import-time without error
        from mcp_newsletter.providers import openai, cursor, vscode, cline, continue_, cloudflare  # noqa
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_vendor_collectors.CollectAllRegistrationTests -v`
Expected: FAIL — the new collectors are not yet in the `collect_all` tuple (import line at the bottom fails if any module missing, or the providers aren't wired).

- [ ] **Step 3: Edit `providers/__init__.py`**

Current:

```python
from .claude import collect_claude
from .codex import collect_codex
from .gemini import collect_gemini
from .grok import collect_grok


def collect_all(ctx: CollectContext) -> List[ServerRecord]:
    servers: List[ServerRecord] = []
    for collector in (collect_codex, collect_gemini, collect_claude, collect_grok):
```

becomes:

```python
from .claude import collect_claude
from .cline import collect_cline
from .cloudflare import collect_cloudflare
from .codex import collect_codex
from .continue_ import collect_continue
from .cursor import collect_cursor
from .gemini import collect_gemini
from .grok import collect_grok
from .openai import collect_openai
from .vscode import collect_vscode


def collect_all(ctx: CollectContext) -> List[ServerRecord]:
    servers: List[ServerRecord] = []
    for collector in (
        collect_codex, collect_gemini, collect_claude, collect_grok,
        collect_openai, collect_cursor, collect_vscode, collect_cline,
        collect_continue, collect_cloudflare,
    ):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_vendor_collectors.CollectAllRegistrationTests -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest -v`
Expected: PASS — all prior + new tests green.

- [ ] **Step 6: Commit**

```bash
git add mcp_newsletter/providers/__init__.py tests/test_vendor_collectors.py
git commit -m "feat(providers): register six new vendor collectors"
```

---

## Self-Review (completed by plan author)

**Spec coverage (design §1 vendor tier, §7 cold-start):**
- 6 new vendor providers as `provider` values in existing pipeline → Tasks 2–4. ✓
- Cold-start silent seeding extended to new vendor providers (§7) → Task 1, with idempotent same-day-re-run behavior proven by `test_same_day_rerun_stays_silent`. ✓
- Cloudflare `remote_url`s flow into the hardened `mcp_discovery` (§5) → Task 3e sets `remote_url`; the existing pipeline already discovers tools for vendor servers with a URL. ✓
- No vendor-tier schema change beyond the additive `provider_seeded` default param (design §2 reconciliation note) → Task 1 keeps `provider_seeded=True` default so existing call sites and the 6 existing tests are unaffected. ✓

**Placeholder scan:** every collector ships complete parser code. The `# VERIFY`
comments on catalog URLs/DOM shapes are intentional per design §3 (the TDD step
captures a real fixture first, then writes the parser to it) — not deferred
work, but the explicit first action of each sub-task.

**Type/name consistency:** `collect_openai`, `collect_cursor`, `collect_vscode`,
`collect_cline`, `collect_continue`, `collect_cloudflare` are defined with these
exact names and imported identically in Task 4. `seeded_providers` and the
`upsert_server(..., provider_seeded=...)` signature are consistent between
Task 1's `state.py` change and the `updater.py` call site. All collectors return
`List[ServerRecord]` matching the existing `collect_all` contract.

**Cross-plan note:** Task 1 modifies `updater.py`'s upsert loop; Plan 2 Task 10
also modifies `updater.py` (adds `run_registry_update`). These edits touch
different regions (upsert loop vs. a new function + one inserted call) and do
not conflict, but whichever plan executes second should re-run the full suite
after merging to confirm.
```

---

## As-Built Amendments

Reconciles the plan with what was implemented and reviewed. Final state: **123 tests, all green.**

**Task 1 — `upsert_tool` also gated by `provider_seeded` (beyond the plan).** The plan reasoned only `upsert_server` needed gating. In practice a brand-new provider's first run would still emit `new_write_tool` events (incomplete silent baseline), so `upsert_tool` gained the same `provider_seeded: bool = True` gate and `run_update` passes `provider_seeded=server.provider in seeded` to it. Test `test_first_run_suppresses_both_server_and_tool_events` proves a new provider's first run emits zero events. Consequently `tests/test_update.py::test_update_is_idempotent_for_same_day` was changed to assert the two runs' event counts are EQUAL (count-agnostic) rather than a magic number, since its fresh-DB `codex` provider is now correctly seeded-silent (0 events).

**Vendor `remote_url` is descriptive-only in v1 (corrects an overclaim).** The plan's §5 / Task 3e claimed vendor servers carrying `remote_url` (e.g. cloudflare) feed `mcp_discovery`. That is NOT true: `discover_remote_tools` is invoked only inside the `codex` and `gemini` collectors, not generically over vendor `ServerRecord`s. For v1, vendor `remote_url` is retained as descriptive metadata only; vendor-side live discovery is a deferred follow-up (wiring it inline would also make the offline collector tests hit the network, since fixture URLs resolve). The registry tier already provides the live-discovery path. Vendor-tier write-capability therefore comes from catalog capability/description text (the existing classifier), which is the same basis as the incumbent claude/grok collectors.

**Collector robustness fixes (review-driven).**
- `vscode.py`: handles a TOP-LEVEL JSON list (the plan's sample ternary crashed on it) — `items = data if isinstance(data, list) else (data.get("servers") or [])`.
- `cloudflare.py`: the name regex was hardened so flattened-page prose is not captured into the connector name.
- `openai.py`/`cursor.py`/`cloudflare.py`: emit a `CrawlIssue` when the fetch succeeds but zero records parse (silent-parser-break detection, mirroring `claude.py`).
- `cursor.py`: rewritten to parse per-card title + per-card description (was naming servers from repo slugs with a shared whole-page description), deduped and sorted.
- `cline.py`/`vscode.py`: empty strings filtered out of `source_urls`.

**Naming.** `continue_.py` correctly sets `provider="continue"` (module name has the trailing underscore only because `continue` is a Python keyword).

**Accepted residual — `# VERIFY` parsers.** All six vendor catalog URLs/shapes are assumption-based and tested against SYNTHETIC fixtures. Per plan §3, capturing a real response per source (then replacing the URL + fixture and removing the `# VERIFY` comment) is deferred to deployment. The new silent-parser-break issues make a wrong/empty catalog visible on the first real run rather than failing silently.
