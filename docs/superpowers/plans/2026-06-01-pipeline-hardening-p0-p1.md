# Pipeline Hardening P0+P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pipeline failures loud (P0 observability) and lay the rendering/extraction foundation for full, clean coverage (P1 core), without disturbing the working daily run.

**Architecture:** Add small, pure, unit-tested modules (`health.py`, `content_extract.py`, `fetch_rendered.py`) and wire them in thinly. All new behavior is additive and env-gated; default behavior is unchanged so the daily job keeps working. Live-network collector repairs are a documented Phase-1b that requires credentials/recon and is out of this offline-verifiable increment.

**Tech Stack:** Python 3, stdlib `unittest` + `unittest.mock`, `urllib` (existing `fetch_text`), optional Firecrawl API / Playwright (env-gated). Tests run with `python3 -m unittest`.

**Status (2026-06-01):** Tasks 1–8 ✅ + **Claude full-directory fix ✅** (24→338, live-verified) complete, committed on branch `feat/pipeline-hardening`, 362 offline tests green (5 live skipped). Remaining **Phase 1b** (repair `openai`/`cursor`/`vscode`/`continue` collectors, public Codex collector, registry keys) still needs live recon and/or `MCP_NEWSLETTER_PULSEMCP_KEY`. Firecrawl key is available (`FIRECRAWL_API_KEY`) for the genuinely-JS sources. P2/P3 follow P1b.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `mcp_newsletter/health.py` | Pure source-health evaluation + run-drop + alert summary | Create [P0] |
| `mcp_newsletter/content_extract.py` | Strip nav/boilerplate; return main content | Create [P1] |
| `mcp_newsletter/fetch_rendered.py` | Backend-abstracted JS-rendering fetch (Firecrawl/Playwright), env-gated | Create [P1] |
| `mcp_newsletter/updater.py` | Compute per-source counts; attach health to status/summary | Modify [P0] |
| `mcp_newsletter/emailer.py` | Thin `send_alert` wrapper for degraded runs | Modify [P0] |
| `mcp_newsletter/providers/codex.py` | Env-driven plugin root default (no `/Users/jon`) | Modify [P0] |
| `mcp_newsletter/providers/claude.py` | Clean descriptions via `content_extract`; optional rendered path | Modify [P1] |
| `tests/test_health.py` | health.py unit tests | Create [P0] |
| `tests/test_content_extract.py` | content_extract.py unit tests | Create [P1] |
| `tests/test_fetch_rendered.py` | fetch_rendered.py unit tests (fake backend) | Create [P1] |
| `tests/test_update_health.py` | run_update attaches health block | Create [P0] |
| `tests/live/test_contract.py` | Live source contract checks, skipped unless `MCP_NEWSLETTER_LIVE_TESTS=1` | Create [P0] |
| `.github/workflows/ci.yml` | Unit on PR/push; scheduled live-contract + smoke | Create [P0] |

---

## Task 1: `health.py` — pure health evaluation

**Files:** Create `mcp_newsletter/health.py`; Test `tests/test_health.py`

- [ ] **Step 1: Write failing tests** (`tests/test_health.py`)

```python
import unittest
from mcp_newsletter.health import evaluate_source_health, run_drop_alert, summarize_health


class HealthTests(unittest.TestCase):
    def test_empty_healthy_source_is_empty(self):
        h = {x.source: x for x in evaluate_source_health({"official": 0}, {"official": 100})}
        self.assertEqual(h["official"].status, "empty")

    def test_below_floor_is_degraded(self):
        h = {x.source: x for x in evaluate_source_health({"claude": 30}, {"claude": 200})}
        self.assertEqual(h["claude"].status, "degraded")

    def test_above_floor_is_ok(self):
        h = {x.source: x for x in evaluate_source_health({"glama": 24000}, {"glama": 1000})}
        self.assertEqual(h["glama"].status, "ok")

    def test_unknown_floor_defaults_to_one(self):
        # a source with no configured floor only flags when truly empty
        h = {x.source: x for x in evaluate_source_health({"newsrc": 0}, {})}
        self.assertEqual(h["newsrc"].status, "empty")

    def test_run_drop_alert_fires_on_big_drop(self):
        self.assertIsNotNone(run_drop_alert(100, 1000, 50.0))

    def test_run_drop_alert_silent_without_prior(self):
        self.assertIsNone(run_drop_alert(100, None, 50.0))

    def test_summarize_marks_degraded_and_builds_alert(self):
        s = summarize_health({"official": 0, "glama": 24000}, {"official": 100, "glama": 1000},
                             total_now=24000, total_prev=50000, drop_pct=50.0)
        self.assertTrue(s["degraded"])
        self.assertIn("official", s["alert"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, verify fail** — `python3 -m unittest tests.test_health -v` → ImportError/FAIL

- [ ] **Step 3: Implement `mcp_newsletter/health.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional


# Conservative defaults; raise claude's floor once P1 rendering lands.
DEFAULT_FLOORS: Dict[str, int] = {
    "official": 100, "glama": 1000, "docker": 50, "smithery": 100,
    "mcpso": 10, "github_servers": 5,
    "claude": 20, "codex": 1, "gemini": 50, "cline": 50, "cloudflare": 5,
}


def floors_from_env(defaults: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    floors = dict(defaults or DEFAULT_FLOORS)
    for source in list(floors):
        raw = os.environ.get(f"MCP_NEWSLETTER_HEALTH_FLOOR_{source.upper()}")
        if raw and raw.strip().isdigit():
            floors[source] = int(raw)
    return floors


@dataclass
class SourceHealth:
    source: str
    count: int
    floor: int
    status: str   # "ok" | "degraded" | "empty"
    message: str


def evaluate_source_health(counts: Dict[str, int], floors: Dict[str, int]) -> List[SourceHealth]:
    sources = sorted(set(counts) | set(floors))
    out: List[SourceHealth] = []
    for source in sources:
        count = int(counts.get(source, 0))
        floor = int(floors.get(source, 1))
        if count <= 0:
            status, msg = "empty", f"{source}: collected 0 (floor {floor}) — source likely broken"
        elif count < floor:
            status, msg = "degraded", f"{source}: {count} < floor {floor} — partial/stale collection"
        else:
            status, msg = "ok", f"{source}: {count} (floor {floor})"
        out.append(SourceHealth(source, count, floor, status, msg))
    return out


def run_drop_alert(total_now: int, total_prev: Optional[int], threshold_pct: float) -> Optional[str]:
    if not total_prev or total_prev <= 0:
        return None
    drop = (total_prev - total_now) / total_prev * 100.0
    if drop >= threshold_pct:
        return f"total records dropped {drop:.0f}% ({total_prev} -> {total_now}, threshold {threshold_pct:.0f}%)"
    return None


def summarize_health(counts, floors, total_now, total_prev, drop_pct) -> Dict[str, object]:
    statuses = evaluate_source_health(counts, floors)
    bad = [s for s in statuses if s.status != "ok"]
    drop = run_drop_alert(total_now, total_prev, drop_pct)
    degraded = bool(bad) or drop is not None
    alert = None
    if degraded:
        parts = [s.message for s in bad]
        if drop:
            parts.append(drop)
        alert = "PIPELINE DEGRADED: " + "; ".join(parts)
    return {
        "degraded": degraded,
        "alert": alert,
        "sources": [s.__dict__ for s in statuses],
    }
```

- [ ] **Step 4: Run, verify pass** — `python3 -m unittest tests.test_health -v` → PASS
- [ ] **Step 5: Commit** — `git add mcp_newsletter/health.py tests/test_health.py && git commit -m "feat(health): pure source-health evaluation + run-drop alert"`

---

## Task 2: Wire health into the run (vendor + registry)

**Files:** Modify `mcp_newsletter/updater.py`; Test `tests/test_update_health.py`

- [ ] **Step 1: Failing test** (`tests/test_update_health.py`) — patch `collect_all` to return one `claude` server, run `run_update(skip_network=True)`, assert `status["health"]["degraded"]` is True (1 claude record < floor 20) and `status["health"]["sources"]` present in `status.json`.

```python
import json, tempfile, unittest
from pathlib import Path
from unittest import mock
from mcp_newsletter.models import ServerRecord
from mcp_newsletter.updater import run_update

def _one_claude(ctx):
    return [ServerRecord(provider="claude", server_id="x", native_surface="connector", name="X")]

class UpdateHealthTests(unittest.TestCase):
    def test_status_has_health_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all", _one_claude):
                run_update(root, run_date="2026-06-01", skip_network=True)
            status = json.loads((root / "data/current/status.json").read_text())
            self.assertIn("health", status)
            self.assertTrue(status["health"]["degraded"])
```

- [ ] **Step 2: Run, verify fail** — `python3 -m unittest tests.test_update_health -v` → KeyError "health"
- [ ] **Step 3: Implement** — in `updater.py`, import `from .health import floors_from_env, summarize_health`; after building `servers`, compute `from collections import Counter` (already imported) `vendor_counts = dict(Counter(s.provider for s in servers))`; read prior total from existing `status.json` if present; build `status["health"] = summarize_health(vendor_counts, floors_from_env(), total_now=len(servers), total_prev=prior_total, drop_pct=float(os.environ.get("MCP_NEWSLETTER_RUN_DROP_ALERT_PCT","50")))`. For each non-ok healthy-source, `ctx.add_issue(source, "health", msg, severity="error")` (so it surfaces in the report's Crawl Issues). Keep registry health additive in `run_registry_update` summary using `collection.counts`.
- [ ] **Step 4: Run, verify pass** — `python3 -m unittest tests.test_update_health -v` → PASS; also run `python3 -m unittest tests.test_update -v` (no regressions)
- [ ] **Step 5: Commit** — `git commit -am "feat(health): attach health block to status + escalate empty sources to issues"`

---

## Task 3: Health alert wrapper (emailer)

**Files:** Modify `mcp_newsletter/emailer.py`

- [ ] **Step 1:** Add `send_alert(subject, body, ...)` mirroring `send_daily_report` SMTP wiring but taking an explicit subject/body (so the degraded-alert can be sent distinctly). Logic is identical SMTP; only message construction differs. No new test beyond import smoke (SMTP send is not unit-tested in this repo; matches existing convention where `send_daily_report` has no unit test).
- [ ] **Step 2:** `python3 -c "from mcp_newsletter.emailer import send_alert"` → no error
- [ ] **Step 3: Commit** — `git commit -am "feat(emailer): send_alert wrapper for degraded-run notifications"`

---

## Task 4: Fix hardcoded Codex plugin path

**Files:** Modify `mcp_newsletter/providers/codex.py:17`

- [ ] **Step 1:** Replace `"/Users/jon/.codex/.tmp/plugins"` default with `str(Path.home() / ".codex" / "plugins")` so it works on any machine; keep `MCP_NEWSLETTER_CODEX_PLUGIN_ROOT` override.
- [ ] **Step 2:** `python3 -m unittest tests.test_vendor_collectors -v` → still PASS
- [ ] **Step 3: Commit** — `git commit -am "fix(codex): default plugin root to ~/.codex/plugins (remove hardcoded /Users/jon)"`

---

## Task 5: `content_extract.py` — main-content extraction

**Files:** Create `mcp_newsletter/content_extract.py`; Test `tests/test_content_extract.py`

- [ ] **Step 1: Failing test** — feed a Claude-like detail page (main content wrapped in `<main>`, plus a nav full of "Try Claude / Contact sales") and assert the extracted text contains the real description and NOT "Contact sales".

```python
import unittest
from mcp_newsletter.content_extract import extract_main_text

PAGE = """
<html><head><title>Acme | Claude</title></head><body>
<nav>Meet Claude Products Claude Claude Code Pricing Try Claude Contact sales</nav>
<main><h1>Acme</h1><p>Acme connects Claude to your warehouse to query and update inventory.</p></main>
<footer>Try Claude Contact sales</footer>
</body></html>
"""

class ContentExtractTests(unittest.TestCase):
    def test_pulls_main_drops_nav(self):
        text = extract_main_text(PAGE)
        self.assertIn("warehouse to query and update inventory", text)
        self.assertNotIn("Contact sales", text)

    def test_falls_back_to_body_when_no_main(self):
        text = extract_main_text("<html><body><p>Just body text here.</p></body></html>")
        self.assertIn("Just body text", text)
```

- [ ] **Step 2: Run, verify fail**
- [ ] **Step 3: Implement** — prefer the innermost `<main>...</main>` (fallback `<article>`, then strip `<nav>/<header>/<footer>/<script>/<style>/<svg>` from `<body>` and use the remainder), then reuse `utils.html_to_text` on the chosen region. Pure function, no network.
- [ ] **Step 4: Run, verify pass**
- [ ] **Step 5: Commit** — `git commit -am "feat(content-extract): main-content extraction to kill nav boilerplate"`

---

## Task 6: `fetch_rendered.py` — backend-abstracted rendered fetch

**Files:** Create `mcp_newsletter/fetch_rendered.py`; Test `tests/test_fetch_rendered.py`

- [ ] **Step 1: Failing test** — with backend `none` (default), returns `(None, meta)` with a "rendering disabled" reason (so daily run is a no-op). With an injected fake backend, returns its markdown. No network.

```python
import unittest
from mcp_newsletter.fetch_rendered import fetch_rendered

class FetchRenderedTests(unittest.TestCase):
    def test_disabled_by_default(self):
        text, meta = fetch_rendered("https://x.test", backend="none")
        self.assertIsNone(text)
        self.assertIn("disabled", meta["error"])

    def test_injected_backend(self):
        text, meta = fetch_rendered("https://x.test", backend="custom",
                                    _backend=lambda url, **k: ("# rendered", {"status": 200}))
        self.assertEqual(text, "# rendered")
        self.assertEqual(meta["status"], 200)
```

- [ ] **Step 2: Run, verify fail**
- [ ] **Step 3: Implement** — `fetch_rendered(url, *, backend=None, _backend=None, **kw)`: backend resolves from arg or `MCP_NEWSLETTER_RENDER_BACKEND` (default `none`). `none` → `(None, {"url":url,"status":None,"error":"rendering disabled (set MCP_NEWSLETTER_RENDER_BACKEND)"})`. `_backend` (injection) called directly. `firecrawl` → POST `https://api.firecrawl.dev/v1/scrape` with `FIRECRAWL_API_KEY`, `{"url":url,"formats":["markdown"]}`, parse `.data.markdown` (lazy, urllib, capped, netguard-respecting). `playwright` → lazy import, headless render, return content. Backends that need creds/libs raise a clear error captured into meta.
- [ ] **Step 4: Run, verify pass**
- [ ] **Step 5: Commit** — `git commit -am "feat(fetch-rendered): env-gated JS rendering (firecrawl/playwright) behind a no-op default"`

---

## Task 7: `claude.py` — clean descriptions (+ optional rendered path)

**Files:** Modify `mcp_newsletter/providers/claude.py`; Test extend `tests/test_vendor_collectors.py` (or new `tests/test_claude_provider.py`)

- [ ] **Step 1: Failing test** — drive `collect_claude` with a `mock.patch` on `CollectContext.fetch` returning a directory page (one detail link) then a nav-polluted detail page; assert the resulting record's `description` contains the real sentence and not "Contact sales".
- [ ] **Step 2: Run, verify fail**
- [ ] **Step 3: Implement** — replace `text = html_to_text(markup)` at `claude.py:75` with `text = extract_main_text(markup)`; keep title logic. Add optional: if `env_bool("MCP_NEWSLETTER_CLAUDE_RENDER")`, fetch the directory + details via `fetch_rendered` first, falling back to `ctx.fetch`. Default path unchanged except for the cleaner description.
- [ ] **Step 4: Run, verify pass** — plus full `python3 -m unittest` (no regressions)
- [ ] **Step 5: Commit** — `git commit -am "feat(claude): clean main-content descriptions + optional rendered collection"`

---

## Task 8: CI + live-contract scaffold

**Files:** Create `.github/workflows/ci.yml`, `tests/live/__init__.py`, `tests/live/test_contract.py`

- [ ] **Step 1:** `tests/live/test_contract.py` — `@unittest.skipUnless(os.environ.get("MCP_NEWSLETTER_LIVE_TESTS")=="1", "live")` class with one test per source asserting a min-count/marker via the real collector. Skipped in normal runs (so offline suite stays green).
- [ ] **Step 2:** `.github/workflows/ci.yml` — job `unit`: checkout, setup-python 3.x, `python3 -m unittest`. job `live` (schedule + workflow_dispatch): same but with `MCP_NEWSLETTER_LIVE_TESTS=1`, `continue-on-error: true` so drift is visible without blocking.
- [ ] **Step 3:** `python3 -m unittest` (confirm live tests are skipped, suite green)
- [ ] **Step 4: Commit** — `git commit -am "ci: add unit workflow + skipped live-contract scaffold"`

---

## Phase 1b — REQUIRES LIVE ACCESS (not in this offline increment)

- ✅ **DONE — Full Claude directory (24→338):** implemented via **plain-HTTP Webflow pagination** (discover the hashed `_page` param, follow server-rendered pages), NOT rendering. Live-verified 338 connectors, 338/338 clean descriptions, **0 Firecrawl credits**. `claude` health floor raised to 300. Key learning: the flagship gap needed pagination, not JS rendering — `fetch_rendered`/Firecrawl is reserved for genuinely-JS sources below.

Still pending (each needs live recon and/or credentials):
- **Repair collectors** `openai`, `cursor`, `vscode`, `continue_`: find the *current* endpoint+shape (try plain pagination first, then `fetch_rendered` via Firecrawl — esp. `cursor` whose 429 a render backend bypasses), rewrite the parser, add a `tests/live` contract assertion + offline fixture test.
- **Public Codex/ChatGPT-apps collector**: replace the local-FS codex reader with a public-surface collector.
- **Registry keys**: obtain `MCP_NEWSLETTER_PULSEMCP_KEY` / `MCP_NEWSLETTER_SMITHERY_KEY`; fix gemini >5MB streaming.

---

## Self-Review

- **Spec coverage (P0/P1):** health floors (T1–2) ✓; alerting (T2–3) ✓; live contract tests + CI (T8) ✓; codex path (T4) ✓; JS rendering (T6) ✓; main-content extraction (T5, T7) ✓; full Claude directory + collector repair + registry holes → Phase 1b (explicitly deferred, needs live access) ✓.
- **Placeholder scan:** new-module tasks carry full code; modify-tasks specify exact edits + line refs. No TBDs.
- **Type consistency:** `summarize_health(counts, floors, total_now, total_prev, drop_pct)`, `evaluate_source_health`, `run_drop_alert`, `extract_main_text(markup)`, `fetch_rendered(url, *, backend, _backend, **kw)` used consistently across tasks and tests.
