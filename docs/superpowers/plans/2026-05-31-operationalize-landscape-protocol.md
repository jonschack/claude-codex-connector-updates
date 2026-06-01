# Operationalize the Landscape Analysis Protocol — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the converged analysis core (`landscape.py`/`landscape_report.py`/`landscape` CLI, initiatives I1–I11) and operationalize it end-to-end so it delivers maximal completeness and accuracy in production — populated verified tiers, full source coverage, the vendor tier folded in, `isLatest` correctness, scheduled report generation, and longitudinal (week-over-week) tracking.

**Architecture:** Three sequential phases on top of the existing tested code. **Phase A** unifies the record view (vendor + registry) and widens/cleans the sources. **Phase B** populates the `verified_tools`/`annotation` evidence tiers at scale by wiring the existing `ground_record_with_tools` into the discovery path and adding Glama per-server tool fetch. **Phase C** schedules the report into the daily/weekly flow and persists a metrics history for diffing. Each phase is an independently-shippable, tested increment.

**Tech Stack:** Python 3.9 stdlib only; `unittest`. Builds on `mcp_newsletter/{landscape.py, landscape_report.py, registries/*, registry_discovery.py, registry_classify.py, updater.py, cli.py}`.

**Reference baseline:** `docs/analysis-protocol/PLAN.md` (the protocol spec + As-Built Amendments). Run `python3 -m unittest` (expect 304 green) before starting.

---

## Decomposition / file map

| Phase | Files created/modified | Responsibility |
|---|---|---|
| A | `landscape_report.py` (loader), new `landscape_ingest.py`, `registries/official.py`, `registries/{docker,github_servers,mcpso,smithery}.py` | Unified record view across both tiers; `isLatest`; verified parser shapes |
| B | `registry_discovery.py`, `updater.py`, `registries/glama.py` | Populate verified/annotation tiers at scale |
| C | `cli.py`, `updater.py`, `landscape_report.py` | Scheduled report + metrics history + week-over-week diff |

Each task is TDD, offline (network mocked), with a commit. The "verify a live parser" tasks (A4–A7) are inherently data-dependent: the deliverable is **capture a real response → write the parser to it → test against the captured fixture** (the exact pattern already used to fix `official`/`glama`).

---

## PHASE A — Unified record view + source completeness

### Task A1: Vendor-record normalizer

**Files:**
- Create: `mcp_newsletter/landscape_ingest.py`
- Test: `tests/test_landscape_ingest.py`

The vendor pipeline writes `data/current/servers.json` whose records have keys
`{provider, server_id, name, description, capabilities, write_confidence, evidence, remote_url, source_urls, native_surface, transport, metadata}` — a DIFFERENT shape from the registry `RegistryServerRecord` the landscape analysis expects (`{identity, name, description, repo_url, remote_url, sources, capabilities, tags, write_confidence, evidence, confidence_by_source}`). Normalize vendor → landscape shape.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_landscape_ingest.py
import unittest
from mcp_newsletter.landscape_ingest import normalize_vendor_record


class NormalizeVendorTests(unittest.TestCase):
    def test_maps_vendor_record_to_landscape_shape(self):
        v = {
            "provider": "claude", "server_id": "linear", "name": "Linear",
            "description": "Create and update issues", "capabilities": ["Read & write"],
            "write_confidence": "high", "evidence": [{"kind": "catalog_capability", "value": ["Read & write"], "confidence": "high"}],
            "remote_url": "https://mcp.linear.app/sse",
            "source_urls": ["https://github.com/linear/mcp", "https://linear.app"],
            "native_surface": "connector", "transport": "mcp", "metadata": {},
        }
        out = normalize_vendor_record(v, run_date="2026-05-31")
        self.assertEqual(out["identity"], "claude:linear")
        self.assertEqual(out["sources"], [{"source": "claude"}])
        self.assertEqual(out["remote_url"], "https://mcp.linear.app/sse")
        self.assertEqual(out["repo_url"], "https://github.com/linear/mcp")  # first github source_url
        self.assertEqual(out["tags"], ["Read & write"])
        self.assertEqual(out["write_confidence"], "high")
        # write_confidence is catalog-derived for vendors:
        self.assertEqual(out["confidence_by_source"]["catalog"]["confidence"], "high")

    def test_no_github_source_url_leaves_repo_empty(self):
        v = {"provider": "grok", "server_id": "gmail", "name": "Gmail", "description": "",
             "capabilities": [], "write_confidence": "unknown", "evidence": [],
             "remote_url": "", "source_urls": ["https://x.ai/docs"], "native_surface": "connector",
             "transport": "catalog", "metadata": {}}
        out = normalize_vendor_record(v, run_date="2026-05-31")
        self.assertEqual(out["repo_url"], "")
        self.assertEqual(out["confidence_by_source"], {})  # unknown → no catalog entry
```

- [ ] **Step 2: Run → fail** — `python3 -m unittest tests.test_landscape_ingest -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement**
```python
# mcp_newsletter/landscape_ingest.py
from __future__ import annotations

import re
from typing import Any, Dict, List

_REPORTABLE = {"medium", "high"}
_GITHUB_RE = re.compile(r"https?://github\.com/", re.I)


def normalize_vendor_record(v: Dict[str, Any], run_date: str) -> Dict[str, Any]:
    """Map a vendor ServerRecord dict (data/current/servers.json) into the
    landscape record shape used by landscape.py. Vendor write-capability is
    catalog/description-derived, so it is recorded under confidence_by_source
    ["catalog"] only when reportable (so evidence_tier yields claimed_description,
    never a false verified_tools)."""
    provider = v.get("provider", "")
    server_id = v.get("server_id", "")
    source_urls: List[str] = v.get("source_urls") or []
    repo_url = next((u for u in source_urls if _GITHUB_RE.match(u or "")), "")
    wc = v.get("write_confidence", "unknown")
    cbs: Dict[str, Any] = {}
    if wc in _REPORTABLE:
        cbs["catalog"] = {"confidence": wc, "date": run_date}
    return {
        "identity": f"{provider}:{server_id}",
        "name": v.get("name", ""),
        "description": v.get("description", ""),
        "repo_url": repo_url,
        "remote_url": v.get("remote_url", ""),
        "sources": [{"source": provider}],
        "capabilities": list(v.get("capabilities") or []),
        "tags": list(v.get("capabilities") or []),
        "write_confidence": wc,
        "evidence": list(v.get("evidence") or []),
        "confidence_by_source": cbs,
    }
```

- [ ] **Step 4: Run → pass.** `python3 -m unittest tests.test_landscape_ingest -v`
- [ ] **Step 5: Commit**
```bash
git add mcp_newsletter/landscape_ingest.py tests/test_landscape_ingest.py
git commit -m "feat(landscape): vendor-record normalizer for unified record view"
```

### Task A2: Unified snapshot loader (registry + vendor)

**Files:**
- Modify: `mcp_newsletter/landscape_report.py` (`load_snapshot`)
- Test: `tests/test_landscape_report.py`

`load_snapshot` currently reads only `registry_state.jsonl`. Add an opt-in `include_vendor=True` that also reads `data/current/servers.json`, normalizes via `normalize_vendor_record`, and concatenates — so the landscape covers BOTH tiers (raising coverage). The vendor records are tagged distinctly (their `sources[].source` is the provider, e.g. `claude`), so coverage/provenance stays correct.

- [ ] **Step 1: Write the failing test**
```python
# add to tests/test_landscape_report.py
import json, tempfile
from pathlib import Path
from mcp_newsletter.landscape_report import load_snapshot

class UnifiedLoaderTests(unittest.TestCase):
    def test_includes_vendor_records_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            cur = Path(tmp) / "data" / "current"; cur.mkdir(parents=True)
            (cur / "registry_state.jsonl").write_text(
                json.dumps({"identity": "io.x/a", "name": "A", "description": "",
                            "repo_url": "", "remote_url": "", "sources": [{"source": "official"}],
                            "capabilities": [], "tags": [], "write_confidence": "unknown",
                            "evidence": [], "confidence_by_source": {}}) + "\n")
            (cur / "registry_summary.json").write_text(json.dumps(
                {"enabled_sources": ["official"], "source_ok": {"official": True},
                 "per_source": {"official": 1}, "per_source_raw": {"official": 1}, "issues": []}))
            (cur / "servers.json").write_text(json.dumps([
                {"provider": "claude", "server_id": "linear", "name": "Linear",
                 "description": "create issues", "capabilities": ["Read & write"],
                 "write_confidence": "high", "evidence": [], "remote_url": "",
                 "source_urls": [], "native_surface": "connector", "transport": "mcp", "metadata": {}}]))
            recs, summ = load_snapshot(Path(tmp), include_vendor=True)
        idents = {r["identity"] for r in recs}
        self.assertIn("io.x/a", idents)
        self.assertIn("claude:linear", idents)

    def test_excludes_vendor_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            cur = Path(tmp) / "data" / "current"; cur.mkdir(parents=True)
            (cur / "registry_state.jsonl").write_text("")
            (cur / "registry_summary.json").write_text(json.dumps(
                {"enabled_sources": [], "source_ok": {}, "per_source": {}, "per_source_raw": {}, "issues": []}))
            (cur / "servers.json").write_text(json.dumps([{"provider": "claude", "server_id": "x", "name": "X",
                 "description": "", "capabilities": [], "write_confidence": "unknown", "evidence": [],
                 "remote_url": "", "source_urls": [], "native_surface": "c", "transport": "c", "metadata": {}}]))
            recs, _ = load_snapshot(Path(tmp))   # default: registry only
        self.assertEqual(recs, [])
```

- [ ] **Step 2: Run → fail** (load_snapshot has no `include_vendor` param / ignores servers.json).

- [ ] **Step 3: Implement** — change `load_snapshot` signature to `load_snapshot(root, include_vendor=False, run_date="")`. After reading registry records, if `include_vendor` and `servers.json` exists, read it and extend with `normalize_vendor_record(v, run_date or summary.get("run_date",""))` for each. Import `from .landscape_ingest import normalize_vendor_record`. Use the summary's `run_date` if present else the passed `run_date`.

- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit**
```bash
git add mcp_newsletter/landscape_report.py tests/test_landscape_report.py
git commit -m "feat(landscape): load_snapshot can fold in the vendor tier (unified record view)"
```

### Task A3: `isLatest` filtering in the official collector

**Files:**
- Modify: `mcp_newsletter/registries/official.py`
- Test: `tests/test_registry_collectors.py`

The official registry returns multiple VERSION rows per server; current dedup collapses by name but keeps whichever version was emitted, so a stored description can be from a stale version. Keep only the row whose `_meta["io.modelcontextprotocol.registry/official"].isLatest` is true (fall back to keeping all when no row is marked latest, preserving current behavior).

- [ ] **Step 1: Write the failing test** — add to `tests/fixtures/registries/official_page1.json` (or a new fixture) a server `io.github.acme/multi` with TWO entries: version 1.0.0 `isLatest:false` (description "old") and 2.0.0 `isLatest:true` (description "new"). Assert `collect_official` yields exactly one entry for `io.github.acme/multi` with description "new".

- [ ] **Step 2: Run → fail** (both versions currently emitted as separate RawRegistryEntry with the same official_name → merge keeps an arbitrary one's description).

- [ ] **Step 3: Implement** — in the per-entry loop, read `is_latest = official_meta.get("isLatest")`. Track, per `name`, whether any latest exists; if a server has any `isLatest:true` row, skip its non-latest rows. Simplest deterministic approach: a first pass to collect the set of `(name)` that have a latest row, then in emission skip rows where `is_latest is False and name in names_with_latest`. Keep rows where `is_latest` is true or unknown.

- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit**
```bash
git add mcp_newsletter/registries/official.py tests/fixtures/registries/ tests/test_registry_collectors.py
git commit -m "fix(registries): official collector keeps only isLatest version per server"
```

### Tasks A4–A7: Verify the remaining registry parsers against live shapes

For each of `docker`, `github_servers`, `mcpso`, `smithery`, the parser is still `# VERIFY` (written to synthetic fixtures). Each task follows the SAME proven procedure used for `official`/`glama`:

- [ ] **Step 1 — Probe the live shape.** Run a one-off probe (do NOT commit it) to capture the real response, e.g.:
```bash
python3 - <<'PY'
import urllib.request, json
url = "<the collector's default URL>"   # from the collector module
req = urllib.request.Request(url, headers={"User-Agent":"mcp-newsletter/0.1","Accept":"application/json"})
body = urllib.request.urlopen(req, timeout=20).read().decode("utf-8","replace")
print(body[:1500])
PY
```
For `smithery` this requires `MCP_NEWSLETTER_SMITHERY_KEY` (graceful-skip path is already correct without it — if no key is available, this task's outcome is "documented as key-gated, parser left key-ready," mirroring PulseMCP). For `docker` the listing is the `docker/mcp-registry` GitHub contents API + per-server `server.yaml`.
- [ ] **Step 2 — Capture a representative fixture** into `tests/fixtures/registries/<source>_live.json` (trimmed to 2–3 entries, secrets removed).
- [ ] **Step 3 — Adapt the parser** in `mcp_newsletter/registries/<source>.py` to the captured field names; remove the `# VERIFY` comment once matched. Preserve the existing guards (throttle, save-after-empty-check, skip_network, graceful-skip, JSON error → issue).
- [ ] **Step 4 — Update the collector test** to assert parsing against the captured fixture (mock `fetch_text`/`_fetch_with_auth`); assert `repo_url`/`remote_url`/`tags` as applicable.
- [ ] **Step 5 — Run the suite green; commit** `fix(registries): <source> parser verified against live API`.

If a source's live API is unreachable/changed (like PulseMCP's v0beta 410), the task outcome is to **record it in `docs/analysis-protocol/PLAN.md` "out of scope" with the observed status** and leave the parser key-ready/graceful — never silently emit garbage.

### Task A8: Document PulseMCP key acquisition + a key-gated smoke path

**Files:**
- Modify: `docs/OPERATIONS.md`, `docs/analysis-protocol/PLAN.md`
- Test: `tests/test_registry_collectors.py` (already has the no-key skip test; add a with-key parse test using a mocked auth fetch returning a generic-registry fixture)

- [ ] **Step 1:** Add a with-key test: set `MCP_NEWSLETTER_PULSEMCP_KEY`, mock the auth fetch to return a wrapped `{server,_meta}` page, assert servers parse and a `deleted` one is skipped.
- [ ] **Step 2:** Document in `docs/OPERATIONS.md` how to obtain the key (`hello@pulsemcp.com`), the env vars (`MCP_NEWSLETTER_PULSEMCP_KEY`, `_TENANT`), and that absence → graceful skip.
- [ ] **Step 3:** Commit `docs+test(registries): pulsemcp key-gated path documented and tested`.

---

## PHASE B — Populate verified/annotation tiers at scale (accuracy)

### Task B1: Wire `ground_record_with_tools` into discovery (populate the `annotation` tier)

**Files:**
- Modify: `mcp_newsletter/registry_discovery.py` (`run_discovery`)
- Test: `tests/test_registry_discovery.py`

`run_discovery` currently sets `rec.confidence_by_source["tools"]` directly and **drops** the per-tool `mcp_annotation` evidence, so the `annotation` evidence tier never populates in production. Route the classified tools through the existing `landscape.ground_record_with_tools`, which both sets the tools confidence AND propagates `mcp_annotation` evidence onto the record.

- [ ] **Step 1: Write the failing test**
```python
# add to tests/test_registry_discovery.py
def test_discovery_propagates_annotation_evidence_to_record(self):
    rec = _rec("a")  # has remote_url
    from mcp_newsletter.models import ToolRecord
    # a tool whose classify_tool will yield mcp_annotation evidence (destructiveHint)
    tool = ToolRecord(provider="registry", server_id="a", name="delete_thing",
                      native_surface="registry", description="Delete a thing",
                      annotations={"destructiveHint": True})
    with mock.patch.object(registry_discovery, "discover_remote_tools",
                           return_value=([tool], {"ok": True})):
        run_discovery([rec], run_date="2026-05-30", workers=2)
    # annotation evidence is now on the record (not just confidence_by_source)
    self.assertTrue(any(e.get("kind") == "mcp_annotation" for e in rec["evidence"])
                    if isinstance(rec, dict) else
                    any(e.get("kind") == "mcp_annotation" for e in rec.evidence))
```
(Note: `run_discovery` operates on `RegistryServerRecord` objects in production but the landscape grounding takes dicts — see Step 3 for the adapter.)

- [ ] **Step 2: Run → fail** (annotation evidence not propagated).

- [ ] **Step 3: Implement** — in `run_discovery`, after classifying tools, replace the direct `rec.confidence_by_source["tools"] = ...` with a call that also propagates annotation evidence. Because `ground_record_with_tools` operates on the landscape dict shape, add a thin local propagation in `registry_discovery` that mirrors it on the `RegistryServerRecord`: set `rec.confidence_by_source["tools"]` to the max tool confidence AND append each tool-evidence item with `kind == "mcp_annotation"` to `rec.evidence` (dedupe by `(kind,value,confidence)`). Keep this logic in one helper `_ground(rec, tools, run_date)` so it stays consistent with `landscape.ground_record_with_tools`.

- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit**
```bash
git add mcp_newsletter/registry_discovery.py tests/test_registry_discovery.py
git commit -m "feat(discovery): propagate mcp_annotation evidence onto records (populates annotation tier)"
```

### Task B2: Population-scale discovery policy + config

**Files:**
- Modify: `mcp_newsletter/updater.py` (`run_registry_update` discovery step), `docs/OPERATIONS.md`
- Test: `tests/test_registry_update.py`

Today discovery is capped (`MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP`, default 150) and rotates by cadence — fine for a daily diff, but to populate `verified_tools` across the population you need a higher cap on a periodic "deep" run. Add a `--deep`-style env knob and document the cadence so verified coverage grows over runs without exploding any single run.

- [ ] **Step 1: Write the failing test** — with `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP=2` and a mocked `run_discovery` (patch `mcp_newsletter.updater.run_discovery`) that records how many candidates it was given, assert the cap is honored; and with the cap unset assert the default (150). (Mock discovery; no network.)

- [ ] **Step 2: Run → fail** if the cap isn't threaded as expected (it is read in updater — the test pins the contract).

- [ ] **Step 3: Implement/confirm** — ensure `run_registry_update` reads the cap and passes `select_discovery_candidates(..., cap, ...)`; add `MCP_NEWSLETTER_REGISTRY_DISCOVERY_WORKERS` (default 8) threaded into `run_discovery(..., workers=...)`. Document in `docs/OPERATIONS.md`: a weekly "deep" run with a high cap (e.g. 1500) + the rotation cadence so the full population is covered over N weeks; daily runs stay light.

- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit** `feat(discovery): configurable cap/workers + documented deep-run cadence`.

### Task B3: Glama per-server tool fetch (verified tier without live discovery)

**Files:**
- Modify: `mcp_newsletter/registries/glama.py`
- Test: `tests/test_registry_collectors.py`

Glama's list endpoint ships `tools: []`, but the per-server detail endpoint includes real `tools[]`. For Glama servers that are write-candidates (description-reportable) and lack live discovery, fetch the detail endpoint to obtain real tools, classify them (`classifier.classify_tool`), and ground the record — moving Glama servers from `claimed_description` → `verified_tools` without arbitrary-host discovery. Bounded by a cap (`MCP_NEWSLETTER_GLAMA_DETAIL_CAP`, default 0 = off; opt-in for deep runs).

- [ ] **Step 1: Probe** the Glama detail endpoint shape (one-off, not committed):
```bash
python3 - <<'PY'
import urllib.request, json
# detail URL pattern — confirm against the live API (e.g. /servers/{namespace}/{slug} or /servers/{id})
url = "https://glama.ai/api/mcp/v1/servers/<namespace>/<slug>"
print(urllib.request.urlopen(url, timeout=20).read().decode()[:1500])
PY
```
- [ ] **Step 2: Capture a fixture** `tests/fixtures/registries/glama_detail.json` (one server with a non-empty `tools[]` incl. a write tool with annotations).
- [ ] **Step 3: Write the failing test** — with `MCP_NEWSLETTER_GLAMA_DETAIL_CAP=5` and `fetch_text` mocked to return the list page then the detail fixture, assert the resulting entry carries the real tool names (folded into the classification text per the existing pattern) and that a write tool is present.
- [ ] **Step 4: Implement** — after the list pull, for up to `GLAMA_DETAIL_CAP` write-candidate servers, fetch the detail endpoint (throttled, skip_network-aware), extract `tools[]`, and fold tool names into the entry's classification text (matching the existing "Tools: …" fold) so downstream grounding/classification sees them.
- [ ] **Step 5: Run → pass; commit** `feat(registries): optional Glama per-server tool fetch for verified-tier coverage`.

---

## PHASE C — Operational integration + longitudinal tracking

### Task C1: `landscape` step wired into the run

**Files:**
- Modify: `mcp_newsletter/cli.py` (the `daily` subcommand), `mcp_newsletter/updater.py`
- Test: `tests/test_landscape_report.py` or `tests/test_registry_update.py`

After `run_update` writes the snapshot, generate the landscape report so it ships with every (deep) run. Add an opt-in `--landscape` flag to `daily` (and a standalone `landscape` already exists). When set, `daily` calls the landscape report builder (no validation network on the daily path; validation is for explicit/weekly runs) and writes `LANDSCAPE_REPORT.md` + `landscape_metrics.json`.

- [ ] **Step 1: Write the failing test** — a `daily`-style flow over a tmp snapshot with `--landscape` (mock collectors, skip-network) asserts `LANDSCAPE_REPORT.md` + `landscape_metrics.json` are written. (Reuse the existing `run_registry_update` test harness to produce the snapshot, then call the landscape builder.)
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — factor a `generate_landscape(root, run_date, include_vendor=True, validate_sample=0, seed=0)` helper in `landscape_report.py` that loads the snapshot (unified), builds the report+metrics, writes both files, returns the metrics. Call it from the `landscape` CLI and (when `--landscape`) from `daily`. Ensure the committed paths include the two landscape outputs (they are under `data/current/`, already in the `git add` set).
- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit** `feat(cli): generate landscape report as part of the daily run (opt-in)`.

### Task C2: Metrics history + week-over-week diff

**Files:**
- Modify: `mcp_newsletter/landscape_report.py`
- Test: `tests/test_landscape_report.py`

Append each run's headline metrics to `data/current/landscape_history.jsonl` (one line per run_date: snapshot_date, total, by_tier, write_capable, coverage %, validation precision/recall) and show a **diff vs the previous entry** in the report (Δ verified-write-capable, Δ coverage). This turns the protocol from a one-shot into the change-tracker it was meant to be, and the committed JSONL git-deltas cheaply.

- [ ] **Step 1: Write the failing test** — `append_history(root, metrics)` writes/appends a line; `latest_prior(root, before_date)` returns the previous run's metrics; `build_report(..., prior_metrics=...)` includes a "Change since {date}" section with the Δs. Test the diff math (e.g. verified 10→14 shows +4) and the no-prior case (first run → "baseline, no prior").
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** the three additions; `generate_landscape` (C1) reads the prior, builds the report with it, then appends the new metrics (in that order, so a run never diffs against itself). `run_date` comes from the snapshot/arg (no wall-clock).
- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit** `feat(landscape): metrics history + week-over-week diff section`.

### Task C3: Persist validation metrics over time

**Files:**
- Modify: `mcp_newsletter/landscape_report.py` (history entry includes validation), `docs/OPERATIONS.md`
- Test: `tests/test_landscape_report.py`

When a run includes `--validate-sample`, store the precision/recall/CI + sample sizes in the history line so the description-heuristic's measured accuracy is tracked over time (and CIs visibly tighten as samples accumulate). Document a recommended weekly `--validate-sample 300 --seed <week>`.

- [ ] **Step 1: Write the failing test** — a history entry built from metrics that include `validation` carries `precision`/`recall`/`answered`; absent validation → those fields are null/omitted, no crash.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — extend the history record + a small "validation trend" line in the report when ≥2 historical validation points exist. Document the weekly validation cadence in `docs/OPERATIONS.md`.
- [ ] **Step 4: Run → pass.** Full suite green.
- [ ] **Step 5: Commit** `feat(landscape): track classifier precision/recall across runs`.

---

## Self-Review (completed by plan author)

**Scope coverage (vs "operationalize end-to-end"):** unified vendor+registry record view (A1–A2) ✓; isLatest correctness (A3) ✓; remaining-parser verification + PulseMCP key (A4–A8) ✓; verified/annotation tiers populated at scale (B1–B3) ✓; scheduled report (C1) ✓; longitudinal diff + validation tracking (C2–C3) ✓. The convergence review's named levers (population discovery, Glama detail tools, isLatest, larger validation, scheduling) all map to tasks.

**Placeholder scan:** the only intentionally data-dependent tasks are A4–A7 and B3 (live-API verification) — these are written as an explicit **probe→capture→adapt→test** procedure (the same one already executed for official/glama), not vague "implement later"; each has concrete steps, a probe script, and a defined fallback (document as key-gated/out-of-scope). All deterministic tasks (A1–A3, A8, B1–B2, C1–C3) carry complete code or exact change descriptions + tests.

**Type/name consistency:** `normalize_vendor_record(v, run_date)` (A1) is consumed by `load_snapshot(..., include_vendor=True, run_date=...)` (A2) and `generate_landscape(...)` (C1). `_ground` (B1) mirrors `landscape.ground_record_with_tools`'s contract (`confidence_by_source["tools"]` + `mcp_annotation` evidence). History helpers `append_history`/`latest_prior`/`build_report(prior_metrics=...)` (C2) are reused by C3. Landscape record shape (`identity/sources/confidence_by_source/...`) is consistent with `landscape.py`'s expectations throughout.

**Phase independence:** A ships a wider, cleaner, unified dataset; B ships populated verified tiers; C ships scheduled longitudinal reporting. Each is green-testable on its own and in order (B depends on A's records; C reports on A+B). Recommend executing A→B→C, reviewing after each (mirrors the protocol's own loop discipline).

**Out-of-scope (unchanged, documented):** PulseMCP remains key-gated; full multi-week population discovery is a runtime cadence, not a code task; coverage % continues to report the gap rather than hide it.
