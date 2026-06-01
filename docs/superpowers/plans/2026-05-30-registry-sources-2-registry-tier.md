# Registry Sources — Plan 2: Registry Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-registry MCP index — collect from 7 ecosystem registries, dedup to one canonical entry per server, classify write-capability, diff against committed JSONL state, and emit a separate "Ecosystem Registries" report section — without touching the existing vendor pipeline.

**Architecture:** A new `mcp_newsletter/registries/` subsystem. Collectors return raw per-source entries plus a success flag; `merge.py` resolves a monorepo-safe identity and unions duplicates; `registry_state.py` loads/writes sorted JSONL state and computes events (new/changed/regressed/delisted) with cold-start seeding and source-down-aware liveness; classification reuses `classifier.py` via a thin tag-normalizer; live discovery is deterministic, capped, and rotates. A new `run_registry_update()` orchestrates it, wired into the existing `update`/`daily` commands.

**Tech Stack:** Python 3 stdlib (`json`, `dataclasses`, `concurrent.futures`, `unittest`). Depends on **Plan 1** (`netguard`, hardened `fetch_text`/`mcp_discovery`).

**Prerequisite:** Plan 1 merged. Run `python3 -m unittest` and confirm green before starting.

---

## File Structure

- **Create** `mcp_newsletter/registries/__init__.py` — `collect_all_registries(ctx) -> RegistryCollection` (try/except per source; records per-source success for liveness). Also a per-host throttle + paginate helper (deferred here from Plan 1).
- **Create** `mcp_newsletter/registries/base.py` — `RawRegistryEntry`, `RegistryServerRecord` dataclasses, `RegistryCollection`, and the `RegistrySource` callable type.
- **Create** `mcp_newsletter/registries/merge.py` — `identity()`, `merge_entries()` with persisted-alias remap.
- **Create** `mcp_newsletter/registries/official.py`, `github_servers.py`, `docker.py`, `pulsemcp.py`, `smithery.py`, `glama.py`, `mcpso.py` — one collector each.
- **Create** `mcp_newsletter/registry_classify.py` — tag-normalizer + `classify_registry_record()`.
- **Create** `mcp_newsletter/registry_discovery.py` — `select_discovery_candidates()` + `run_discovery()` (bounded thread pool, main-thread-safe results).
- **Create** `mcp_newsletter/registry_state.py` — JSONL load/write + `diff_and_events()` + a small meta store.
- **Create** `mcp_newsletter/registry_reporting.py` — `render_registry_section()`.
- **Modify** `mcp_newsletter/updater.py` — add `run_registry_update()`, call it from `run_update`.
- **Modify** `mcp_newsletter/gitops.py:55` — commit explicit registry text outputs, not raw bundles.
- **Modify** `.gitignore` — ignore raw registry snapshot bundles.
- **Tests:** `tests/test_registry_merge.py`, `tests/test_registry_state.py`, `tests/test_registry_discovery.py`, `tests/test_registry_classify.py`, `tests/test_registry_collectors.py`, `tests/test_registry_reporting.py`, `tests/test_registry_update.py`, plus fixtures under `tests/fixtures/registries/`.

**Canonical output files (committed, text):**
- `data/current/registry_state.jsonl` — one record per line, sorted by identity (diff source of truth).
- `data/current/registry_events.json` — today's events.
- `data/current/registry_summary.json` — counts + enabled-source map.
- `data/current/registry_evidence.md` — plain-text evidence manifest for emitted events.

**Local-only (gitignored):** `data/snapshots/<date>/registries/*` raw page bundles.

**Env config:** `MCP_NEWSLETTER_REGISTRIES` (allowlist; default all), `MCP_NEWSLETTER_<SOURCE>_URL`/`_KEY`/`_MAX`, `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP` (150), `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS` (3), `MCP_NEWSLETTER_REGISTRY_DELIST_RUNS` (3), `MCP_NEWSLETTER_REGISTRY_HOST_THROTTLE` (0.2s), `MCP_NEWSLETTER_REGISTRY_TIME_BUDGET_SEC` (1800).

---

## Task 1: Data model — `base.py`

**Files:**
- Create: `mcp_newsletter/registries/__init__.py` (empty for now: `# registry tier`)
- Create: `mcp_newsletter/registries/base.py`
- Test: `tests/test_registry_merge.py` (model roundtrip portion)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry_merge.py
import unittest

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryServerRecord


class ModelTests(unittest.TestCase):
    def test_record_jsonl_roundtrip_is_stable(self):
        rec = RegistryServerRecord(
            identity="io.github.acme/slack",
            name="Slack",
            description="Send messages",
            repo_url="https://github.com/acme/slack",
            remote_url="https://mcp.acme.com/slack",
            sources=[{"source": "official", "source_id": "io.github.acme/slack",
                      "source_url": "https://registry...", "tags": ["chat"], "last_updated": "2026-05-30"}],
            capabilities=["Write"],
            tags=["chat"],
            write_confidence="high",
            confidence_by_source={"catalog": {"confidence": "high", "date": "2026-05-30"}},
        )
        line = rec.to_jsonl()
        back = RegistryServerRecord.from_jsonl(line)
        self.assertEqual(back.to_jsonl(), line)
        self.assertEqual(back.identity, "io.github.acme/slack")

    def test_raw_entry_defaults(self):
        entry = RawRegistryEntry(source="glama", source_id="acme/slack", name="Slack")
        self.assertEqual(entry.tags, [])
        self.assertEqual(entry.repo_url, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_registry_merge.ModelTests -v`
Expected: FAIL `ModuleNotFoundError: ... registries.base`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/registries/__init__.py
# registry tier
```

```python
# mcp_newsletter/registries/base.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class RawRegistryEntry:
    """One server as seen in ONE registry, before dedup."""
    source: str
    source_id: str
    name: str
    description: str = ""
    repo_url: str = ""
    remote_url: str = ""
    subpath: str = ""
    official_name: str = ""          # reverse-DNS name if the source provides one
    tags: List[str] = field(default_factory=list)
    last_updated: str = ""
    source_url: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegistryServerRecord:
    """Canonical, deduped server across registries."""
    identity: str
    name: str
    description: str = ""
    repo_url: str = ""
    remote_url: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    write_confidence: str = "unknown"
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    # confidence remembered per evidence source: {"tools": {"confidence","date"}, "catalog": {...}}
    confidence_by_source: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity,
            "name": self.name,
            "description": self.description,
            "repo_url": self.repo_url,
            "remote_url": self.remote_url,
            "sources": sorted(self.sources, key=lambda s: s.get("source", "")),
            "capabilities": sorted(set(self.capabilities)),
            "tags": sorted(set(self.tags)),
            "write_confidence": self.write_confidence,
            "evidence": self.evidence,
            "confidence_by_source": self.confidence_by_source,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)

    @classmethod
    def from_jsonl(cls, line: str) -> "RegistryServerRecord":
        data = json.loads(line)
        return cls(
            identity=data["identity"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            repo_url=data.get("repo_url", ""),
            remote_url=data.get("remote_url", ""),
            sources=data.get("sources", []),
            capabilities=data.get("capabilities", []),
            tags=data.get("tags", []),
            write_confidence=data.get("write_confidence", "unknown"),
            evidence=data.get("evidence", []),
            confidence_by_source=data.get("confidence_by_source", {}),
        )


@dataclass
class RegistryCollection:
    entries: List[RawRegistryEntry] = field(default_factory=list)
    # source name -> succeeded this run (False freezes liveness for that source)
    source_ok: Dict[str, bool] = field(default_factory=dict)


# A collector takes the CollectContext and returns its raw entries.
RegistrySource = Callable[[Any], List[RawRegistryEntry]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_registry_merge.ModelTests -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registries/__init__.py mcp_newsletter/registries/base.py tests/test_registry_merge.py
git commit -m "feat(registries): add raw/canonical data model"
```

---

## Task 2: Identity resolution — `merge.identity`

**Files:**
- Create: `mcp_newsletter/registries/merge.py`
- Test: `tests/test_registry_merge.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_registry_merge.py
from mcp_newsletter.registries.merge import identity
from mcp_newsletter.registries.base import RawRegistryEntry


class IdentityTests(unittest.TestCase):
    def test_official_name_wins(self):
        e = RawRegistryEntry(source="official", source_id="x", name="Slack",
                             official_name="io.github.acme/slack",
                             repo_url="https://github.com/acme/slack")
        self.assertEqual(identity(e), "io.github.acme/slack")

    def test_repo_with_subpath_distinguishes_monorepo_servers(self):
        e1 = RawRegistryEntry(source="glama", source_id="a", name="Fetch",
                              repo_url="https://github.com/modelcontextprotocol/servers",
                              subpath="src/fetch")
        e2 = RawRegistryEntry(source="glama", source_id="b", name="Git",
                              repo_url="https://github.com/modelcontextprotocol/servers",
                              subpath="src/git")
        self.assertNotEqual(identity(e1), identity(e2))
        self.assertTrue(identity(e1).endswith("#src/fetch"))

    def test_repo_without_subpath_uses_repo_root(self):
        e = RawRegistryEntry(source="glama", source_id="a", name="Solo",
                             repo_url="https://github.com/acme/solo")
        self.assertEqual(identity(e), "repo:github.com/acme/solo")

    def test_repo_url_normalized(self):
        e = RawRegistryEntry(source="glama", source_id="a", name="Solo",
                             repo_url="https://GitHub.com/Acme/Solo.git/")
        self.assertEqual(identity(e), "repo:github.com/acme/solo")

    def test_fallback_to_source_slug(self):
        e = RawRegistryEntry(source="mcpso", source_id="weather-thing", name="Weather Thing")
        self.assertEqual(identity(e), "mcpso:weather-thing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_registry_merge.IdentityTests -v`
Expected: FAIL `ModuleNotFoundError: ... merge`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/registries/merge.py
from __future__ import annotations

import re
from typing import Dict, List

from ..utils import slugify
from .base import RawRegistryEntry, RegistryServerRecord


def _normalize_repo(repo_url: str) -> str:
    """github.com/acme/solo  (host lowercased, scheme/.git/trailing slash stripped)."""
    if not repo_url:
        return ""
    url = repo_url.strip()
    url = re.sub(r"^https?://", "", url, flags=re.I)
    url = url.rstrip("/")
    url = re.sub(r"\.git$", "", url, flags=re.I)
    # drop /tree/<ref>/... or /blob/... suffixes
    url = re.sub(r"/(tree|blob)/.*$", "", url)
    parts = url.split("/")
    if parts:
        parts[0] = parts[0].lower()  # host only
    return "/".join(p for p in parts if p).lower()


def identity(entry: RawRegistryEntry) -> str:
    if entry.official_name:
        return entry.official_name
    repo = _normalize_repo(entry.repo_url)
    if repo:
        if entry.subpath:
            return f"repo:{repo}#{entry.subpath.strip('/')}"
        return f"repo:{repo}"
    return f"{entry.source}:{slugify(entry.name or entry.source_id)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_registry_merge.IdentityTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registries/merge.py tests/test_registry_merge.py
git commit -m "feat(registries): monorepo-safe identity resolution"
```

---

## Task 3: Merge & alias remap — `merge.merge_entries`

**Files:**
- Modify: `mcp_newsletter/registries/merge.py`
- Test: `tests/test_registry_merge.py`

Alias keys are **high-specificity only** (official name, `repo#subpath`) — never `remote_url`. `aliases` is `{alias_key: canonical_identity}` loaded from prior state; a record matching an existing alias reuses that canonical identity (stability across runs).

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_registry_merge.py
from mcp_newsletter.registries.merge import merge_entries


class MergeTests(unittest.TestCase):
    def test_same_server_across_sources_collapses_to_one(self):
        entries = [
            RawRegistryEntry(source="official", source_id="x", name="Slack",
                             official_name="io.github.acme/slack",
                             repo_url="https://github.com/acme/slack", tags=["chat"]),
            RawRegistryEntry(source="glama", source_id="acme/slack", name="Slack MCP",
                             repo_url="https://github.com/acme/slack", subpath="",
                             official_name="io.github.acme/slack", tags=["messaging"]),
        ]
        records = merge_entries(entries, aliases={})
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.identity, "io.github.acme/slack")
        self.assertEqual({s["source"] for s in rec.sources}, {"official", "glama"})
        self.assertIn("chat", rec.tags)
        self.assertIn("messaging", rec.tags)

    def test_monorepo_servers_stay_separate(self):
        entries = [
            RawRegistryEntry(source="glama", source_id="a", name="Fetch",
                             repo_url="https://github.com/modelcontextprotocol/servers",
                             subpath="src/fetch"),
            RawRegistryEntry(source="glama", source_id="b", name="Git",
                             repo_url="https://github.com/modelcontextprotocol/servers",
                             subpath="src/git"),
        ]
        records = merge_entries(entries, aliases={})
        self.assertEqual(len(records), 2)

    def test_alias_remaps_to_prior_canonical_identity(self):
        # a server first known by repo identity; now also carries an official name.
        entries = [
            RawRegistryEntry(source="official", source_id="x", name="Slack",
                             official_name="io.github.acme/slack",
                             repo_url="https://github.com/acme/slack"),
        ]
        aliases = {"repo:github.com/acme/slack": "repo:github.com/acme/slack"}
        records = merge_entries(entries, aliases=aliases)
        # The repo alias already maps to the older canonical id, so reuse it
        self.assertEqual(records[0].identity, "repo:github.com/acme/slack")

    def test_output_sorted_by_identity(self):
        entries = [
            RawRegistryEntry(source="mcpso", source_id="z", name="Zebra"),
            RawRegistryEntry(source="mcpso", source_id="a", name="Apple"),
        ]
        records = merge_entries(entries, aliases={})
        ids = [r.identity for r in records]
        self.assertEqual(ids, sorted(ids))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_registry_merge.MergeTests -v`
Expected: FAIL `ImportError: cannot import name 'merge_entries'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to mcp_newsletter/registries/merge.py

def _alias_keys(entry: RawRegistryEntry) -> List[str]:
    """High-specificity alias keys only — never remote_url."""
    keys = []
    if entry.official_name:
        keys.append(entry.official_name)
    repo = _normalize_repo(entry.repo_url)
    if repo:
        keys.append(f"repo:{repo}#{entry.subpath.strip('/')}" if entry.subpath else f"repo:{repo}")
    return keys


def _resolve_identity(entry: RawRegistryEntry, aliases: Dict[str, str]) -> str:
    for key in _alias_keys(entry):
        if key in aliases:
            return aliases[key]
    return identity(entry)


def merge_entries(entries: List[RawRegistryEntry], aliases: Dict[str, str]) -> List[RegistryServerRecord]:
    by_id: Dict[str, RegistryServerRecord] = {}
    for entry in entries:
        ident = _resolve_identity(entry, aliases)
        rec = by_id.get(ident)
        source_row = {
            "source": entry.source,
            "source_id": entry.source_id,
            "source_url": entry.source_url,
            "tags": sorted(set(entry.tags)),
            "last_updated": entry.last_updated,
        }
        if rec is None:
            rec = RegistryServerRecord(
                identity=ident,
                name=entry.name,
                description=entry.description,
                repo_url=entry.repo_url,
                remote_url=entry.remote_url,
                sources=[source_row],
                tags=list(entry.tags),
            )
            by_id[ident] = rec
            continue
        rec.sources.append(source_row)
        rec.tags = sorted(set(rec.tags + entry.tags))
        if len(entry.description) > len(rec.description):
            rec.description = entry.description
        if not rec.repo_url and entry.repo_url:
            rec.repo_url = entry.repo_url
        if not rec.remote_url and entry.remote_url:
            rec.remote_url = entry.remote_url
    return [by_id[k] for k in sorted(by_id)]


def build_alias_map(records: List[RegistryServerRecord]) -> Dict[str, str]:
    """Persisted next run: every high-specificity key -> canonical identity."""
    aliases: Dict[str, str] = {}
    for rec in records:
        aliases[rec.identity] = rec.identity
        repo = _normalize_repo(rec.repo_url)
        if repo:
            aliases.setdefault(f"repo:{repo}", rec.identity)
    return aliases
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_registry_merge.MergeTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registries/merge.py tests/test_registry_merge.py
git commit -m "feat(registries): dedup/merge with stable alias remap"
```

---

## Task 4: Tag-normalizer + classification — `registry_classify.py`

**Files:**
- Create: `mcp_newsletter/registry_classify.py`
- Test: `tests/test_registry_classify.py`

Reuses `classifier.classify_catalog`. The normalizer maps known write-implying
tags into capability phrases the classifier already understands, then records
the result under a named evidence source so regression logic (Task 6) can
compare like-for-like.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_registry_classify.py
import unittest

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_classify import classify_registry_record, tags_to_capabilities


class RegistryClassifyTests(unittest.TestCase):
    def test_write_tag_maps_to_write_capability(self):
        caps = tags_to_capabilities(["productivity", "write"])
        self.assertIn("Write", caps)

    def test_action_tag_maps_to_write(self):
        caps = tags_to_capabilities(["automation"])
        self.assertIn("Write", caps)

    def test_read_only_tag_does_not_imply_write(self):
        caps = tags_to_capabilities(["search", "read"])
        self.assertNotIn("Write", caps)

    def test_classify_records_catalog_evidence_source(self):
        rec = RegistryServerRecord(identity="x", name="Sender",
                                   description="Send and post messages", tags=[])
        classify_registry_record(rec, run_date="2026-05-30")
        self.assertIn(rec.write_confidence, {"medium", "high"})
        self.assertIn("catalog", rec.confidence_by_source)
        self.assertEqual(rec.confidence_by_source["catalog"]["date"], "2026-05-30")

    def test_tool_evidence_source_recorded_when_tools_classified(self):
        rec = RegistryServerRecord(identity="x", name="X")
        rec.confidence_by_source = {"tools": {"confidence": "high", "date": "2026-05-29"}}
        classify_registry_record(rec, run_date="2026-05-30")
        # effective confidence takes max across non-stale sources
        self.assertEqual(rec.write_confidence, "high")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_registry_classify -v`
Expected: FAIL `ModuleNotFoundError: ... registry_classify`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/registry_classify.py
from __future__ import annotations

from typing import List

from .classifier import RANK, classify_catalog
from .registries.base import RegistryServerRecord

# Tags/categories that imply the server can take action.
WRITE_TAGS = {
    "write", "automation", "actions", "productivity", "crm", "email",
    "messaging", "calendar", "deploy", "devops", "payments", "ecommerce",
    "project-management", "ticketing", "social",
}


def tags_to_capabilities(tags: List[str]) -> List[str]:
    lowered = {t.strip().lower() for t in tags}
    return ["Write"] if (lowered & WRITE_TAGS) else []


def _max_conf(a: str, b: str) -> str:
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def classify_registry_record(rec: RegistryServerRecord, run_date: str) -> None:
    """Set rec.write_confidence from catalog evidence (tags + capabilities +
    description), combined with any previously stored tool evidence.

    Records the catalog result under confidence_by_source['catalog'] with today's
    date. Tool evidence (confidence_by_source['tools']) is set elsewhere by the
    discovery step; here we only read it so confidence never drops merely because
    tools were not re-discovered this run.
    """
    caps = sorted(set(rec.capabilities) | set(tags_to_capabilities(rec.tags)))
    rec.capabilities = caps
    catalog_conf, evidence = classify_catalog(caps, rec.description)
    rec.confidence_by_source["catalog"] = {"confidence": catalog_conf, "date": run_date}
    rec.evidence = evidence

    effective = "unknown"
    for source in ("catalog", "tools"):
        info = rec.confidence_by_source.get(source)
        if info:
            effective = _max_conf(effective, info["confidence"])
    rec.write_confidence = effective
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_registry_classify -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registry_classify.py tests/test_registry_classify.py
git commit -m "feat(registries): tag-aware classification with per-source confidence"
```

---

## Task 5: Discovery selection + runner — `registry_discovery.py`

**Files:**
- Create: `mcp_newsletter/registry_discovery.py`
- Test: `tests/test_registry_discovery.py`

`select_discovery_candidates` is pure (deterministic ordering + cap + cadence).
`run_discovery` uses a bounded thread pool but workers ONLY fetch/parse and
return data; the caller applies results on the main thread (SQLite/state not
thread-safe).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_registry_discovery.py
import unittest

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_discovery import select_discovery_candidates


def _rec(identity, remote=True):
    return RegistryServerRecord(
        identity=identity, name=identity,
        remote_url=("https://8.8.8.8/" + identity) if remote else "",
    )


class SelectTests(unittest.TestCase):
    def test_only_records_with_remote_url(self):
        recs = [_rec("a", remote=True), _rec("b", remote=False)]
        sel = select_discovery_candidates(recs, cap=10, last_discovered={},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual([r.identity for r in sel], ["a"])

    def test_never_discovered_first_then_stable_by_identity(self):
        recs = [_rec("c"), _rec("a"), _rec("b")]
        last = {"a": "2026-05-30", "c": "2026-05-30"}  # b never discovered
        sel = select_discovery_candidates(recs, cap=10, last_discovered=last,
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual(sel[0].identity, "b")  # never-discovered wins

    def test_cap_limits_count(self):
        recs = [_rec(x) for x in "abcde"]
        sel = select_discovery_candidates(recs, cap=2, last_discovered={},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual(len(sel), 2)

    def test_recently_discovered_within_cadence_skipped(self):
        recs = [_rec("a")]
        sel = select_discovery_candidates(recs, cap=10,
                                          last_discovered={"a": "2026-05-29"},
                                          cadence_days=3, run_date="2026-05-30")
        self.assertEqual(sel, [])  # discovered 1 day ago, cadence 3 days

    def test_deterministic_across_calls(self):
        recs = [_rec(x) for x in "edcba"]
        a = select_discovery_candidates(recs, cap=3, last_discovered={},
                                        cadence_days=3, run_date="2026-05-30")
        b = select_discovery_candidates(recs, cap=3, last_discovered={},
                                        cadence_days=3, run_date="2026-05-30")
        self.assertEqual([r.identity for r in a], [r.identity for r in b])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_registry_discovery -v`
Expected: FAIL `ModuleNotFoundError: ... registry_discovery`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/registry_discovery.py
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from .mcp_discovery import discover_remote_tools
from .registries.base import RegistryServerRecord


def _days_between(a: str, b: str) -> int:
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    except ValueError:
        return 10 ** 6


def select_discovery_candidates(
    records: List[RegistryServerRecord],
    cap: int,
    last_discovered: Dict[str, str],
    cadence_days: int,
    run_date: str,
) -> List[RegistryServerRecord]:
    """Deterministic, capped, rotating selection of remote servers to probe."""
    eligible = []
    for rec in records:
        if not rec.remote_url:
            continue
        seen = last_discovered.get(rec.identity)
        if seen and _days_between(seen, run_date) < cadence_days:
            continue  # discovered recently; let it rotate later
        eligible.append(rec)

    def sort_key(rec: RegistryServerRecord):
        never = 0 if rec.identity not in last_discovered else 1
        last = last_discovered.get(rec.identity, "")
        return (never, last, rec.identity)

    eligible.sort(key=sort_key)
    return eligible[:cap]


def run_discovery(
    candidates: List[RegistryServerRecord],
    run_date: str,
    workers: int = 8,
    timeout: int = 15,
) -> Dict[str, str]:
    """Probe candidates concurrently. Workers only fetch/parse. Returns
    {identity: discovered_date} for those probed; mutates each record's
    confidence_by_source['tools'] on the MAIN thread after the pool joins.
    """
    from .classifier import classify_tool, max_confidence

    def probe(rec: RegistryServerRecord) -> Tuple[str, list, dict]:
        tools, result = discover_remote_tools("registry", rec.identity, "registry", rec.remote_url, timeout=timeout)
        return rec.identity, tools, result

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, rec) for rec in candidates]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:  # one bad endpoint must not kill the batch
                continue

    by_id = {rec.identity: rec for rec in candidates}
    discovered: Dict[str, str] = {}
    for identity, tools, result in results:
        rec = by_id.get(identity)
        if rec is None:
            continue
        discovered[identity] = run_date
        if result.get("ok") and tools:
            confs = []
            for tool in tools:
                tool.write_confidence, tool.evidence = classify_tool(tool)
                confs.append(tool.write_confidence)
            rec.confidence_by_source["tools"] = {"confidence": max_confidence(confs), "date": run_date}
    return discovered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_registry_discovery -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registry_discovery.py tests/test_registry_discovery.py
git commit -m "feat(registries): deterministic rotating capped discovery"
```

---

## Task 6: State, diff & events — `registry_state.py`

**Files:**
- Create: `mcp_newsletter/registry_state.py`
- Test: `tests/test_registry_state.py`

This is the correctness core: JSONL load/write, cold-start seeding, the four
event types, source-down-aware liveness, and like-for-like regression.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_registry_state.py
import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_state import (
    RegistryMeta, diff_and_events, load_state, write_state,
)


def _rec(identity, conf="high", sources=("official",)):
    return RegistryServerRecord(
        identity=identity, name=identity, write_confidence=conf,
        sources=[{"source": s} for s in sources],
        confidence_by_source={"catalog": {"confidence": conf, "date": "2026-05-30"}},
    )


class StateIoTests(unittest.TestCase):
    def test_jsonl_roundtrip_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry_state.jsonl"
            write_state(path, [_rec("z"), _rec("a")])
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            loaded = load_state(path)
            self.assertEqual(sorted(loaded), ["a", "z"])


class DiffTests(unittest.TestCase):
    def _meta(self, **kw):
        m = RegistryMeta()
        m.seeded_sources = kw.get("seeded", {"official": "2026-05-01"})
        m.liveness = kw.get("liveness", {})
        m.last_discovered = kw.get("last_discovered", {})
        return m

    def test_cold_start_seeds_silently(self):
        meta = RegistryMeta()  # nothing seeded yet
        events, _new_state, new_meta = diff_and_events(
            prior={}, current={"a": _rec("a")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual(events, [])  # silent baseline
        self.assertIn("official", new_meta.seeded_sources)

    def test_new_write_server_after_baseline(self):
        meta = self._meta()
        events, *_ = diff_and_events(
            prior={}, current={"a": _rec("a")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual([e["event_type"] for e in events], ["new_write_server"])

    def test_status_changed_low_to_high(self):
        meta = self._meta()
        prior = {"a": _rec("a", conf="low")}
        events, *_ = diff_and_events(
            prior=prior, current={"a": _rec("a", conf="high")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual([e["event_type"] for e in events], ["write_status_changed"])

    def test_regression_only_on_like_for_like(self):
        meta = self._meta()
        # prior was high via TOOLS; current has no fresh tool evidence -> must NOT regress
        prior_rec = _rec("a", conf="high")
        prior_rec.confidence_by_source = {"tools": {"confidence": "high", "date": "2026-05-20"}}
        cur = _rec("a", conf="low")  # only catalog says low now; tools absent
        cur.confidence_by_source = {"catalog": {"confidence": "low", "date": "2026-05-30"}}
        events, *_ = diff_and_events(
            prior={"a": prior_rec}, current={"a": cur}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual(events, [])  # no regression: evidence sources differ

    def test_regression_fires_on_same_source_drop(self):
        meta = self._meta()
        prior_rec = _rec("a", conf="high")
        prior_rec.confidence_by_source = {"catalog": {"confidence": "high", "date": "2026-05-29"}}
        cur = _rec("a", conf="low")
        cur.confidence_by_source = {"catalog": {"confidence": "low", "date": "2026-05-30"}}
        events, *_ = diff_and_events(
            prior={"a": prior_rec}, current={"a": cur}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual([e["event_type"] for e in events], ["write_status_regressed"])

    def test_delist_after_threshold_when_source_succeeded(self):
        meta = self._meta(liveness={"a": 2})  # already missed twice
        # current is empty; carrying source 'official' succeeded -> 3rd miss -> delist
        events, _ns, new_meta = diff_and_events(
            prior={"a": _rec("a")}, current={}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertIn("delisted", [e["event_type"] for e in events])

    def test_no_delist_when_carrying_source_failed(self):
        meta = self._meta(liveness={"a": 2})
        events, *_ = diff_and_events(
            prior={"a": _rec("a")}, current={}, run_date="2026-05-30",
            source_ok={"official": False}, meta=meta, delist_runs=3,
        )
        self.assertNotIn("delisted", [e["event_type"] for e in events])

    def test_new_source_when_server_appears_in_additional_registry(self):
        meta = self._meta()
        prior = {"a": _rec("a", sources=("official",))}
        current = {"a": _rec("a", sources=("official", "glama"))}
        events, *_ = diff_and_events(
            prior=prior, current=current, run_date="2026-05-30",
            source_ok={"official": True, "glama": True}, meta=meta, delist_runs=3,
        )
        new_source = [e for e in events if e["event_type"] == "new_source"]
        self.assertEqual(len(new_source), 1)
        self.assertIn("glama", new_source[0]["summary"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_registry_state -v`
Expected: FAIL `ModuleNotFoundError: ... registry_state`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/registry_state.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .classifier import RANK, reportable
from .registries.base import RegistryServerRecord
from .utils import ensure_dir


def load_state(path: Path) -> Dict[str, RegistryServerRecord]:
    if not path.exists():
        return {}
    out: Dict[str, RegistryServerRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = RegistryServerRecord.from_jsonl(line)
        out[rec.identity] = rec
    return out


def write_state(path: Path, records: List[RegistryServerRecord]) -> None:
    ensure_dir(path.parent)
    lines = [rec.to_jsonl() for rec in sorted(records, key=lambda r: r.identity)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


@dataclass
class RegistryMeta:
    seeded_sources: Dict[str, str] = field(default_factory=dict)   # source -> first seeded date
    liveness: Dict[str, int] = field(default_factory=dict)         # identity -> consecutive misses
    last_discovered: Dict[str, str] = field(default_factory=dict)  # identity -> date

    @classmethod
    def load(cls, path: Path) -> "RegistryMeta":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            seeded_sources=data.get("seeded_sources", {}),
            liveness=data.get("liveness", {}),
            last_discovered=data.get("last_discovered", {}),
        )

    def dump(self, path: Path) -> None:
        ensure_dir(path.parent)
        path.write_text(json.dumps({
            "seeded_sources": self.seeded_sources,
            "liveness": self.liveness,
            "last_discovered": self.last_discovered,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _event(run_date, event_type, rec, summary, prev=None):
    return {
        "run_date": run_date,
        "event_type": event_type,
        "identity": rec.identity,
        "confidence": rec.write_confidence,
        "summary": summary,
        "evidence": rec.evidence,
        "sources": sorted({s.get("source", "") for s in rec.sources}),
    }


def _carrying_sources(rec: RegistryServerRecord) -> List[str]:
    return sorted({s.get("source", "") for s in rec.sources})


def diff_and_events(
    prior: Dict[str, RegistryServerRecord],
    current: Dict[str, RegistryServerRecord],
    run_date: str,
    source_ok: Dict[str, bool],
    meta: RegistryMeta,
    delist_runs: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, RegistryServerRecord], RegistryMeta]:
    events: List[Dict[str, Any]] = []

    # Which sources had a successful run THIS time (determines seeding + liveness).
    successful_sources = {s for s, ok in source_ok.items() if ok}
    first_seed = {s for s in successful_sources if s not in meta.seeded_sources}
    for s in first_seed:
        meta.seeded_sources[s] = run_date

    def source_is_seeded(rec) -> bool:
        # A record is "past baseline" if any of its carrying sources was seeded
        # on an earlier run (not just this one).
        for s in _carrying_sources(rec):
            seeded_on = meta.seeded_sources.get(s)
            if seeded_on and seeded_on < run_date:
                return True
        return False

    # --- additions / changes / regressions ---
    for identity in sorted(current):
        rec = current[identity]
        prev = prior.get(identity)
        if prev is None:
            if reportable(rec.write_confidence) and source_is_seeded(rec):
                events.append(_event(run_date, "new_write_server", rec,
                                     f"New write-capable server: {rec.name}"))
            continue
        # status change up
        if not reportable(prev.write_confidence) and reportable(rec.write_confidence):
            events.append(_event(run_date, "write_status_changed", rec,
                                 f"Server became write-capable: {rec.name}"))
            continue
        # regression — only when a SHARED evidence source dropped
        if reportable(prev.write_confidence) and not reportable(rec.write_confidence):
            if _regressed_like_for_like(prev, rec):
                events.append(_event(run_date, "write_status_regressed", rec,
                                     f"Server lost write capability: {rec.name}"))
        # new_source — an existing write-capable server now appears in a registry
        # it was not seen in before (low-noise; reported as a count, not a row)
        if reportable(rec.write_confidence):
            prev_sources = {s.get("source") for s in prev.sources}
            cur_sources = {s.get("source") for s in rec.sources}
            added = sorted(cur_sources - prev_sources)
            if added:
                events.append(_event(run_date, "new_source", rec,
                                     f"{rec.name} newly listed in: {', '.join(added)}"))

    # --- liveness / delisting ---
    new_state = dict(current)
    for identity in sorted(prior):
        if identity in current:
            meta.liveness.pop(identity, None)
            continue
        prev = prior[identity]
        # Only count a miss if at least one of its carrying sources succeeded.
        if not (set(_carrying_sources(prev)) & successful_sources):
            new_state[identity] = prev   # source down: keep, freeze liveness
            continue
        misses = meta.liveness.get(identity, 0) + 1
        if misses >= delist_runs:
            if reportable(prev.write_confidence):
                events.append(_event(run_date, "delisted", prev,
                                     f"Write-capable server delisted: {prev.name}"))
            meta.liveness.pop(identity, None)
            # dropped from new_state (truly gone)
        else:
            meta.liveness[identity] = misses
            new_state[identity] = prev

    events.sort(key=lambda e: (e["event_type"], e["identity"]))
    return events, new_state, meta


def _regressed_like_for_like(prev: RegistryServerRecord, cur: RegistryServerRecord) -> bool:
    """True only if a source present in BOTH dropped from reportable to not."""
    for source, prev_info in prev.confidence_by_source.items():
        cur_info = cur.confidence_by_source.get(source)
        if not cur_info:
            continue  # source absent this run -> not comparable -> no regression
        if reportable(prev_info["confidence"]) and not reportable(cur_info["confidence"]):
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_registry_state -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registry_state.py tests/test_registry_state.py
git commit -m "feat(registries): JSONL state, events, liveness, regression"
```

---

## Task 7: Pagination helper + `collect_all_registries` + official collector

**Files:**
- Modify: `mcp_newsletter/registries/__init__.py`
- Create: `mcp_newsletter/registries/official.py`
- Create: `tests/fixtures/registries/official_page1.json`
- Test: `tests/test_registry_collectors.py`

The official MCP Registry is the canonical source and the worked example for the
collector pattern. The per-host throttle deferred from Plan 1 lives in the
`paginate` helper here.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/registries/official_page1.json`:

```json
{
  "servers": [
    {
      "name": "io.github.acme/slack",
      "description": "Send and read Slack messages",
      "repository": {"url": "https://github.com/acme/slack", "subfolder": ""},
      "remotes": [{"type": "streamable-http", "url": "https://mcp.acme.com/slack"}],
      "status": "active",
      "_meta": {"tags": ["messaging"]}
    },
    {
      "name": "io.github.acme/readonly",
      "description": "Search the docs",
      "repository": {"url": "https://github.com/acme/readonly"},
      "status": "active"
    },
    {
      "name": "io.github.acme/gone",
      "description": "old",
      "status": "deleted"
    }
  ],
  "metadata": {"next_cursor": null}
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_registry_collectors.py
import json
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.context import CollectContext
from mcp_newsletter.registries.official import collect_official

FIX = Path(__file__).parent / "fixtures" / "registries"


def _ctx(tmp):
    return CollectContext(root=Path(tmp), run_date="2026-05-30", skip_network=False)


class OfficialCollectorTests(unittest.TestCase):
    def test_parses_active_servers_and_skips_deleted(self):
        page = (FIX / "official_page1.json").read_text()
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch("mcp_newsletter.registries.official.fetch_text",
                            return_value=(page, {"status": 200, "content_type": "application/json", "error": ""})):
                entries = collect_official(ctx)
        names = {e.official_name for e in entries}
        self.assertIn("io.github.acme/slack", names)
        self.assertNotIn("io.github.acme/gone", names)  # status=deleted skipped
        slack = next(e for e in entries if e.official_name == "io.github.acme/slack")
        self.assertEqual(slack.remote_url, "https://mcp.acme.com/slack")
        self.assertEqual(slack.repo_url, "https://github.com/acme/slack")
        self.assertIn("messaging", slack.tags)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest tests.test_registry_collectors -v`
Expected: FAIL `ModuleNotFoundError: ... registries.official`

- [ ] **Step 4: Write the pagination helper**

Append to `mcp_newsletter/registries/__init__.py`:

```python
from __future__ import annotations

import os
import time
from typing import Callable, Dict, List

from ..context import CollectContext
from .base import RawRegistryEntry, RegistryCollection


_LAST_HOST_HIT: Dict[str, float] = {}


def throttle(host: str) -> None:
    interval = float(os.environ.get("MCP_NEWSLETTER_REGISTRY_HOST_THROTTLE", "0.2"))
    last = _LAST_HOST_HIT.get(host, 0.0)
    now = time.monotonic()
    wait = interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_HOST_HIT[host] = time.monotonic()


def enabled_sources() -> List[str]:
    allow = os.environ.get("MCP_NEWSLETTER_REGISTRIES", "")
    all_sources = ["official", "github_servers", "docker", "pulsemcp", "smithery", "glama", "mcpso"]
    if not allow.strip():
        return all_sources
    wanted = {s.strip() for s in allow.split(",") if s.strip()}
    return [s for s in all_sources if s in wanted]


def collect_all_registries(ctx: CollectContext) -> RegistryCollection:
    from .official import collect_official
    from .github_servers import collect_github_servers
    from .docker import collect_docker
    from .pulsemcp import collect_pulsemcp
    from .smithery import collect_smithery
    from .glama import collect_glama
    from .mcpso import collect_mcpso

    registry = {
        "official": collect_official,
        "github_servers": collect_github_servers,
        "docker": collect_docker,
        "pulsemcp": collect_pulsemcp,
        "smithery": collect_smithery,
        "glama": collect_glama,
        "mcpso": collect_mcpso,
    }
    budget = float(os.environ.get("MCP_NEWSLETTER_REGISTRY_TIME_BUDGET_SEC", "1800"))
    started = time.monotonic()
    collection = RegistryCollection()
    for name in enabled_sources():
        if time.monotonic() - started > budget:
            ctx.add_issue(name, "time-budget",
                          f"skipped: run exceeded {budget:.0f}s time budget", severity="warning")
            collection.source_ok[name] = False  # not run -> freezes liveness (no false delist)
            continue
        collector = registry[name]
        try:
            entries = collector(ctx)
            collection.entries.extend(entries)
            collection.source_ok[name] = True
        except Exception as exc:  # one source failing must not break the run
            ctx.add_issue(name, "registry-collector", repr(exc), severity="error")
            collection.source_ok[name] = False
    return collection
```

- [ ] **Step 5: Write the official collector**

```python
# mcp_newsletter/registries/official.py
from __future__ import annotations

import json
import os
from typing import List

from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry

PROVIDER = "official"
BASE_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


def collect_official(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_OFFICIAL_URL", BASE_URL)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_OFFICIAL_MAX", "20000"))
    entries: List[RawRegistryEntry] = []
    cursor = ""
    page = 0
    while len(entries) < max_servers:
        url = base + (f"?cursor={cursor}" if cursor else "")
        if ctx.skip_network:
            ctx.add_issue(PROVIDER, url, "network skipped")
            break
        text, meta = fetch_text(url)
        ctx.save_raw_text(PROVIDER, f"page-{page}", text or "", ext="json")
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error") or meta.get("status")))
            break
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        for server in data.get("servers", []):
            if server.get("status") == "deleted":
                continue
            repo = (server.get("repository") or {})
            remotes = server.get("remotes") or []
            entries.append(RawRegistryEntry(
                source=PROVIDER,
                source_id=server.get("name", ""),
                official_name=server.get("name", ""),
                name=server.get("name", "").split("/")[-1] or server.get("name", ""),
                description=server.get("description", ""),
                repo_url=repo.get("url", ""),
                subpath=repo.get("subfolder", "") or "",
                remote_url=(remotes[0].get("url", "") if remotes else ""),
                tags=list((server.get("_meta") or {}).get("tags", [])),
                last_updated=server.get("updated_at", ""),
                source_url=base,
                raw=server,
            ))
        cursor = (data.get("metadata") or {}).get("next_cursor")
        page += 1
        if not cursor:
            break
    return entries
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m unittest tests.test_registry_collectors -v`
Expected: PASS (1 test)

- [ ] **Step 7: Commit**

```bash
git add mcp_newsletter/registries/__init__.py mcp_newsletter/registries/official.py tests/fixtures/registries/official_page1.json tests/test_registry_collectors.py
git commit -m "feat(registries): official MCP registry collector + pagination/throttle"
```

---

## Task 8: Remaining six collectors

Each collector returns `List[RawRegistryEntry]` and is registered in Task 7's
`registry` map. Each gets a fixture + one parse test in
`tests/test_registry_collectors.py`. **The exact API field names for PulseMCP,
Glama, and Smithery must be verified against their live responses at
implementation time** (design §3) — capture a real response into the fixture
first, then write the parser to it.

Implement these as **one sub-task each** following the same 5-step TDD rhythm as
Task 7 (fixture → failing test → parser → pass → commit). Concrete parser bodies:

- [ ] **8a — `github_servers.py`** (parse the reference README's server list)

```python
# mcp_newsletter/registries/github_servers.py
from __future__ import annotations
import os
from typing import List
from ..context import CollectContext
from ..utils import extract_github_repos, fetch_text
from .base import RawRegistryEntry

PROVIDER = "github_servers"
README_URL = "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/README.md"


def collect_github_servers(ctx: CollectContext) -> List[RawRegistryEntry]:
    url = os.environ.get("MCP_NEWSLETTER_GITHUB_SERVERS_URL", README_URL)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, url, "network skipped")
        return []
    text, meta = fetch_text(url)
    ctx.save_raw_text(PROVIDER, "readme", text or "", ext="md")
    if not text:
        ctx.add_issue(PROVIDER, url, str(meta.get("error")))
        return []
    entries = []
    for repo in extract_github_repos(text):
        name = repo.rstrip("/").split("/")[-1]
        # monorepo: the reference servers live under modelcontextprotocol/servers
        subpath = ""
        entries.append(RawRegistryEntry(
            source=PROVIDER, source_id=repo, name=name,
            repo_url=repo, subpath=subpath, source_url=url,
        ))
    return entries
```

- [ ] **8b — `docker.py`** (read `docker/mcp-registry` server YAML via raw GitHub; parse the directory listing JSON from the GitHub contents API, then each `server.yaml`). Use `fetch_text` + `json`/a tiny YAML key scan (stdlib has no YAML; parse the few needed keys with regex on the fetched `server.yaml`).

```python
# mcp_newsletter/registries/docker.py
from __future__ import annotations
import json, os, re
from typing import List
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry

PROVIDER = "docker"
CONTENTS_API = "https://api.github.com/repos/docker/mcp-registry/contents/servers"
RAW = "https://raw.githubusercontent.com/docker/mcp-registry/main/servers/{name}/server.yaml"


def _yaml_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, flags=re.M)
    return m.group(1).strip().strip('"\'') if m else ""


def collect_docker(ctx: CollectContext) -> List[RawRegistryEntry]:
    listing_url = os.environ.get("MCP_NEWSLETTER_DOCKER_URL", CONTENTS_API)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, listing_url, "network skipped")
        return []
    text, meta = fetch_text(listing_url)
    ctx.save_raw_text(PROVIDER, "listing", text or "", ext="json")
    if not text:
        ctx.add_issue(PROVIDER, listing_url, str(meta.get("error")))
        return []
    try:
        listing = json.loads(text)
    except json.JSONDecodeError:
        ctx.add_issue(PROVIDER, listing_url, "invalid listing JSON")
        return []
    entries = []
    for item in listing:
        if item.get("type") != "dir":
            continue
        name = item["name"]
        yurl = RAW.format(name=name)
        ybody, _ = fetch_text(yurl)
        if not ybody:
            continue
        ctx.save_raw_text(PROVIDER, f"{name}-server", ybody, ext="yaml")
        entries.append(RawRegistryEntry(
            source=PROVIDER, source_id=name, name=name,
            description=_yaml_value(ybody, "longLived") or _yaml_value(ybody, "description"),
            repo_url=_yaml_value(ybody, "source") or _yaml_value(ybody, "repository"),
            tags=[c.strip() for c in _yaml_value(ybody, "category").split(",") if c.strip()],
            source_url=yurl,
        ))
    return entries
```

- [ ] **8c — `pulsemcp.py`**, **8d — `glama.py`**, **8e — `smithery.py`** (paginated JSON APIs; **verify field names** against a captured fixture). Common shape:

```python
# mcp_newsletter/registries/pulsemcp.py   (glama.py / smithery.py mirror this with their URLs/fields)
from __future__ import annotations
import json, os
from typing import List
from ..context import CollectContext
from ..utils import fetch_text
from .base import RawRegistryEntry

PROVIDER = "pulsemcp"
BASE = "https://api.pulsemcp.com/v0beta/servers"  # VERIFY exact path/fields at implementation


def collect_pulsemcp(ctx: CollectContext) -> List[RawRegistryEntry]:
    base = os.environ.get("MCP_NEWSLETTER_PULSEMCP_URL", BASE)
    max_servers = int(os.environ.get("MCP_NEWSLETTER_PULSEMCP_MAX", "20000"))
    entries, offset = [], 0
    while len(entries) < max_servers and not ctx.skip_network:
        url = f"{base}?count_per_page=100&offset={offset}"
        text, meta = fetch_text(url)
        ctx.save_raw_text(PROVIDER, f"page-{offset}", text or "", ext="json")
        if not text:
            ctx.add_issue(PROVIDER, url, str(meta.get("error")))
            break
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            ctx.add_issue(PROVIDER, url, "invalid JSON page")
            break
        servers = data.get("servers", [])
        if not servers:
            break
        for s in servers:
            entries.append(RawRegistryEntry(
                source=PROVIDER, source_id=s.get("name", ""), name=s.get("name", ""),
                description=s.get("short_description", "") or s.get("description", ""),
                repo_url=s.get("source_code_url", "") or s.get("github_url", ""),
                remote_url=s.get("remote_url", "") or "",
                tags=list(s.get("categories", []) or []),
                source_url=base,
            ))
        if not data.get("next") and len(servers) < 100:
            break
        offset += 100
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, base, "network skipped")
    return entries
```

For `glama.py`: `BASE = "https://glama.ai/api/mcp/v1/servers"`, env `MCP_NEWSLETTER_GLAMA_URL`/`_MAX`, cursor pagination via `pageInfo.endCursor`; map `repository.url` → `repo_url`, `attributes`/`tags` → tags. For `smithery.py`: `BASE = "https://registry.smithery.ai/servers"`, env `MCP_NEWSLETTER_SMITHERY_URL`/`_MAX`/`_KEY`; **if `MCP_NEWSLETTER_SMITHERY_KEY` is unset, add an info issue and `return []`** (do not fail); send `Authorization: Bearer <key>` (extend `fetch_text` call with a header-capable variant or set via a request — capture the exact contract in the fixture first).

- [ ] **8f — `mcpso.py`** (HTML scrape; most fragile)

```python
# mcp_newsletter/registries/mcpso.py
from __future__ import annotations
import os
from typing import List
from ..context import CollectContext
from ..utils import extract_github_repos, fetch_text
from .base import RawRegistryEntry

PROVIDER = "mcpso"
URL = "https://mcp.so/servers"


def collect_mcpso(ctx: CollectContext) -> List[RawRegistryEntry]:
    url = os.environ.get("MCP_NEWSLETTER_MCPSO_URL", URL)
    if ctx.skip_network:
        ctx.add_issue(PROVIDER, url, "network skipped")
        return []
    text, meta = fetch_text(url)
    ctx.save_raw_text(PROVIDER, "listing", text or "", ext="html")
    if not text:
        ctx.add_issue(PROVIDER, url, str(meta.get("error")))
        return []
    entries = []
    for repo in extract_github_repos(text):
        name = repo.rstrip("/").split("/")[-1]
        entries.append(RawRegistryEntry(source=PROVIDER, source_id=repo, name=name,
                                        repo_url=repo, source_url=url))
    return entries
```

- [ ] **Per-collector tests:** for each of 8a–8f, add a fixture under
  `tests/fixtures/registries/<source>_*.json|.md|.html` captured from a real
  response, and a test mirroring `OfficialCollectorTests` (mock `fetch_text` to
  return the fixture; assert the parsed entry's `repo_url`/`remote_url`/`tags`).

- [ ] **Commit** after each collector:

```bash
git add mcp_newsletter/registries/<source>.py tests/fixtures/registries/ tests/test_registry_collectors.py
git commit -m "feat(registries): add <source> collector"
```

---

## Task 9: Reporting — `registry_reporting.py`

**Files:**
- Create: `mcp_newsletter/registry_reporting.py`
- Test: `tests/test_registry_reporting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry_reporting.py
import unittest

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_reporting import render_registry_section


class ReportingTests(unittest.TestCase):
    def _recs(self):
        return {
            "a": RegistryServerRecord(identity="a", name="Slack", write_confidence="high",
                                      sources=[{"source": "official"}, {"source": "glama"}]),
            "b": RegistryServerRecord(identity="b", name="ReadOnly", write_confidence="low",
                                      sources=[{"source": "glama"}]),
        }

    def test_section_has_counts_and_double_count_note(self):
        events = [{"event_type": "new_write_server", "identity": "a",
                   "confidence": "high", "summary": "New write-capable server: Slack",
                   "sources": ["official", "glama"]}]
        out = render_registry_section(
            run_date="2026-05-30", records=self._recs(), events=events,
            enabled=["official", "glama"], per_source={"official": 1, "glama": 2},
            new_source_count=0, row_cap=25,
        )
        self.assertIn("## Ecosystem Registries", out)
        self.assertIn("Indexed servers (deduped): 2", out)
        self.assertIn("Write-capable", out)
        self.assertIn("both the vendor", out.lower() if False else out)  # double-count note present
        self.assertIn("new_write_server", out)

    def test_rows_capped(self):
        events = [{"event_type": "new_write_server", "identity": str(i),
                   "confidence": "high", "summary": f"s{i}", "sources": ["official"]}
                  for i in range(40)]
        out = render_registry_section("2026-05-30", self._recs(), events,
                                      ["official"], {"official": 40}, 0, row_cap=25)
        self.assertIn("additional", out)  # overflow pointer present


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_registry_reporting -v`
Expected: FAIL `ModuleNotFoundError: ... registry_reporting`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_newsletter/registry_reporting.py
from __future__ import annotations

from typing import Any, Dict, List

from .classifier import reportable
from .registries.base import RegistryServerRecord

DOUBLE_COUNT_NOTE = (
    "- Note: a server may also appear in the vendor-tier coverage above; the "
    "two tiers are counted independently."
)


def render_registry_section(
    run_date: str,
    records: Dict[str, RegistryServerRecord],
    events: List[Dict[str, Any]],
    enabled: List[str],
    per_source: Dict[str, int],
    new_source_count: int,
    row_cap: int = 25,
) -> str:
    write_capable = [r for r in records.values() if reportable(r.write_confidence)]
    new_today = [e for e in events if e["event_type"] in {"new_write_server", "write_status_changed"}]

    lines = [
        "## Ecosystem Registries",
        "",
        f"- Indexed servers (deduped): {len(records)} across {len(enabled)} registries",
        f"- Write-capable (medium+): {len(write_capable)}",
        f"- New/changed write-capable today: {len(new_today)}",
    ]
    if per_source:
        per = " · ".join(f"{s} {per_source.get(s, 0)}" for s in sorted(per_source))
        lines.append(f"- Per registry (sums exceed deduped total): {per}")
    if new_source_count:
        lines.append(f"- Existing write-capable servers newly seen in another registry: {new_source_count}")
    lines.append(DOUBLE_COUNT_NOTE)
    lines.append("")

    table_events = [e for e in events if e["event_type"] != "new_source"]
    if table_events:
        lines += [
            "### New / changed / delisted write-capable servers",
            "",
            "| Event | Server | Confidence | Seen in | Summary |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in table_events[:row_cap]:
            lines.append(
                "| {et} | `{id}` | {conf} | {src} | {sm} |".format(
                    et=e["event_type"], id=e["identity"], conf=e["confidence"],
                    src=", ".join(e.get("sources", [])),
                    sm=e["summary"].replace("|", "\\|"),
                )
            )
        if len(table_events) > row_cap:
            lines.append(f"- ... {len(table_events) - row_cap} additional event(s); see `data/current/registry_events.json`.")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_registry_reporting -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_newsletter/registry_reporting.py tests/test_registry_reporting.py
git commit -m "feat(registries): ecosystem report section"
```

---

## Task 10: Orchestration — `run_registry_update` + wiring

**Files:**
- Modify: `mcp_newsletter/updater.py`
- Modify: `mcp_newsletter/gitops.py:55`
- Modify: `.gitignore`
- Test: `tests/test_registry_update.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry_update.py
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcp_newsletter.registries.base import RawRegistryEntry, RegistryCollection
from mcp_newsletter.updater import run_registry_update


def fake_collect(ctx):
    return RegistryCollection(
        entries=[
            RawRegistryEntry(source="official", source_id="io.x/sender",
                             official_name="io.x/sender", name="Sender",
                             description="Send and post messages",
                             repo_url="https://github.com/x/sender"),
        ],
        source_ok={"official": True},
    )


class RegistryUpdateTests(unittest.TestCase):
    def test_first_run_seeds_silently_then_emits_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mcp_newsletter.updater.collect_all_registries", fake_collect):
                first = run_registry_update(root, run_date="2026-05-30", skip_network=True)
                self.assertEqual(first["event_count"], 0)  # cold-start silent
                self.assertTrue((root / "data" / "current" / "registry_state.jsonl").exists())
                second = run_registry_update(root, run_date="2026-05-31", skip_network=True)
            self.assertGreaterEqual(second["event_count"], 1)  # now past baseline


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_registry_update -v`
Expected: FAIL `ImportError: cannot import name 'run_registry_update'`

- [ ] **Step 3: Add `run_registry_update` to `updater.py`**

Add imports at the top of `mcp_newsletter/updater.py`:

```python
import os
from .registries import collect_all_registries, enabled_sources
from .registries.merge import merge_entries, build_alias_map
from .registry_classify import classify_registry_record
from .registry_discovery import select_discovery_candidates, run_discovery
from .registry_state import RegistryMeta, diff_and_events, load_state, write_state
from .registry_reporting import render_registry_section
from collections import Counter
```

Append this function to `updater.py`:

```python
def run_registry_update(root: Path, run_date: Optional[str] = None, skip_network: bool = False) -> Dict[str, object]:
    run_date = run_date or today_iso()
    ensure_dir(root / "data" / "current")
    ctx = CollectContext(root=root, run_date=run_date, skip_network=skip_network)

    state_path = root / "data" / "current" / "registry_state.jsonl"
    meta_path = root / "data" / "current" / "registry_meta.json"
    prior = load_state(state_path)
    meta = RegistryMeta.load(meta_path)
    aliases = build_alias_map(list(prior.values()))

    collection = collect_all_registries(ctx)
    records = merge_entries(collection.entries, aliases)

    # carry prior tool-evidence forward so confidence doesn't drop on un-discovered servers
    current = {rec.identity: rec for rec in records}
    for identity, rec in current.items():
        if identity in prior:
            prior_tools = prior[identity].confidence_by_source.get("tools")
            if prior_tools:
                rec.confidence_by_source.setdefault("tools", prior_tools)

    # live discovery (deterministic, capped, rotating)
    if not skip_network:
        cap = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP", "150"))
        cadence = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS", "3"))
        candidates = select_discovery_candidates(list(current.values()), cap, meta.last_discovered, cadence, run_date)
        discovered = run_discovery(candidates, run_date)
        meta.last_discovered.update(discovered)

    for rec in current.values():
        classify_registry_record(rec, run_date)

    delist_runs = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DELIST_RUNS", "3"))
    events, new_state, meta = diff_and_events(prior, current, run_date, collection.source_ok, meta, delist_runs)

    # persist (state + meta written together; report derived from them)
    write_state(state_path, list(new_state.values()))
    meta.dump(meta_path)
    write_json(root / "data" / "current" / "registry_events.json", events)
    per_source = Counter(s for rec in current.values() for s in {x.get("source") for x in rec.sources})
    summary = {
        "run_date": run_date,
        "indexed": len(new_state),
        "write_capable": sum(1 for r in new_state.values() if r.write_confidence in {"medium", "high"}),
        "event_count": len(events),
        "enabled_sources": enabled_sources(),
        "source_ok": collection.source_ok,
        "per_source": dict(per_source),
        "issues": [i.to_dict() for i in ctx.issues],
    }
    write_json(root / "data" / "current" / "registry_summary.json", summary)

    new_source_count = sum(1 for e in events if e["event_type"] == "new_source")
    section = render_registry_section(run_date, new_state, events, enabled_sources(), dict(per_source), new_source_count)
    write_text(root / "data" / "current" / "registry_section.md", section)
    # distinct manifest label so this does NOT clobber run_update's _run/manifest.json
    ctx.save_raw_json("_run", "registry-manifest", {
        "run_date": run_date,
        "issues": [i.to_dict() for i in ctx.issues],
        "source_ok": collection.source_ok,
    })
    return {"event_count": len(events), "indexed": len(new_state), "section": section}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_registry_update -v`
Expected: PASS (1 test)

- [ ] **Step 5: Call it from `run_update` and append the section to the report**

In `run_update`, after `write_text(root / "reports" / f"{run_date}.md", report)` and before `write_text(root / "README.md", ...)`, add:

```python
    registry_result = run_registry_update(root, run_date=run_date, skip_network=skip_network)
    full_report = report.rstrip() + "\n\n" + registry_result["section"]
    write_text(root / "reports" / f"{run_date}.md", full_report)
    report = full_report
```

- [ ] **Step 6: Update `.gitignore` and `gitops.py`**

Append to `.gitignore`:

```
data/snapshots/*/registries/
```

In `mcp_newsletter/gitops.py:55`, the `git add` line currently lists `data` wholesale. Leave `data` (so `data/current/*.jsonl|json` and reports are committed) — the new `.gitignore` entry keeps the raw registry bundles out. Confirm with a test run that `git status` shows the committed text outputs but not `data/snapshots/<date>/registries/`.

- [ ] **Step 7: Run the full suite**

Run: `python3 -m unittest -v`
Expected: PASS — all prior + new registry tests green.

- [ ] **Step 8: Commit**

```bash
git add mcp_newsletter/updater.py mcp_newsletter/gitops.py .gitignore tests/test_registry_update.py
git commit -m "feat(registries): orchestrate registry update and wire into run_update"
```

---

## Self-Review (completed by plan author)

**Spec coverage (design §2–§11):**
- Two-tier separation; registry subsystem package → Tasks 1–10. ✓
- Monorepo-safe identity + alias remap (§4) → Tasks 2–3. ✓
- High-specificity alias keys (never `remote_url`) → Task 3 `_alias_keys`. ✓
- SSRF/size cap (§5) → inherited from Plan 1; discovery uses hardened `discover_remote_tools`. ✓
- Deterministic rotating capped discovery (§5) → Task 5. ✓
- Thread-pool workers fetch-only; results applied on main thread (§5) → Task 5 `run_discovery` returns data, mutation happens after join. ✓
- Tag-normalizer + per-evidence-source confidence + TTL semantics (§6) → Tasks 4 & 6 (`_regressed_like_for_like`, carry-forward of `tools` evidence in Task 10). ✓
- Sorted JSONL committed state; no registry binary (§7) → Task 6 `write_state`. ✓
- Events new/changed/regressed/delisted + new_source; deterministic ordering (§7) → Task 6 (`new_source` emission + `events.sort`); reporting renders new_source as a count. ✓
- Soft per-run time budget bounding wall-clock (§3) → Task 7 `collect_all_registries` deadline check; budget-skipped sources freeze liveness (no false delist). ✓
- Cold-start silent seeding (§7) → Task 6 + Task 10 test. ✓
- Source-down-aware liveness (§7) → Task 6 `successful_sources` gate. ✓
- Parser-break floor (§7) → **GAP: not yet a task.** Added as Task 11 below.
- Reporting section + double-count note + row cap (§8) → Task 9. ✓
- gitignore raw bundles, commit text outputs (§9) → Task 10 Step 6. ✓
- Per-host throttle (§5, deferred from Plan 1) → Task 7 `throttle`. *Note:* defined but not yet called inside each paginator's loop — wire `throttle(urlparse(url).hostname)` before each `fetch_text` in the paginating collectors during Task 7/8.
- Evidence manifest `registry_evidence.md` (§9) → **GAP: not yet emitted.** Folded into Task 11 below.

**Placeholder scan:** PulseMCP/Glama/Smithery field names are explicitly marked "verify against a captured fixture" per design §3 (intentional, not a placeholder — the TDD step is "capture real response → write parser to it"). No other gaps.

**Type/name consistency:** `RawRegistryEntry`, `RegistryServerRecord`, `RegistryCollection`, `RegistryMeta`, `identity`, `merge_entries`, `build_alias_map`, `classify_registry_record`, `select_discovery_candidates`, `run_discovery`, `diff_and_events`, `load_state`/`write_state`, `render_registry_section`, `collect_all_registries`, `enabled_sources` — all defined before use and referenced identically across tasks. `confidence_by_source` shape `{source: {"confidence","date"}}` is consistent in Tasks 4, 6, 10.

### Task 11: Parser-break floor + evidence manifest (closes the two self-review gaps)

**Files:**
- Modify: `mcp_newsletter/registries/__init__.py` (post-collection floor check)
- Modify: `mcp_newsletter/updater.py` (emit `registry_evidence.md`)
- Test: `tests/test_registry_collectors.py`, `tests/test_registry_update.py`

- [ ] **Step 1: Failing test — floor demotes a suspiciously-empty source**

```python
# add to tests/test_registry_collectors.py
from mcp_newsletter.registries import apply_source_floor

class FloorTests(unittest.TestCase):
    def test_known_large_source_returning_zero_is_marked_failed(self):
        ok = {"official": True}
        counts = {"official": 0}
        apply_source_floor(ok, counts, history={"official": 1400}, first_run=False)
        self.assertFalse(ok["official"])  # frozen: parser likely broke

    def test_legitimately_small_source_not_demoted(self):
        ok = {"docker": True}
        counts = {"docker": 180}
        apply_source_floor(ok, counts, history={"docker": 200}, first_run=False)
        self.assertTrue(ok["docker"])

    def test_first_run_uses_absolute_minimum(self):
        ok = {"official": True}
        apply_source_floor(ok, {"official": 0}, history={}, first_run=True)
        self.assertFalse(ok["official"])  # below built-in absolute floor
```

- [ ] **Step 2: Run → fail.** `ImportError: cannot import name 'apply_source_floor'`

- [ ] **Step 3: Implement** (append to `registries/__init__.py`)

```python
ABSOLUTE_FLOOR = {"official": 100, "glama": 500, "pulsemcp": 500, "smithery": 200}


def apply_source_floor(source_ok: Dict[str, bool], counts: Dict[str, int],
                       history: Dict[str, int], first_run: bool) -> None:
    """Demote a source to failed (freeze liveness) if its count collapsed,
    which usually means a parser broke rather than the catalog emptying."""
    for source, ok in list(source_ok.items()):
        if not ok:
            continue
        n = counts.get(source, 0)
        if first_run:
            if n < ABSOLUTE_FLOOR.get(source, 0):
                source_ok[source] = False
        else:
            prev = history.get(source, 0)
            if prev >= 50 and n < max(1, prev // 5):  # dropped > 80%
                source_ok[source] = False
```

Wire into `collect_all_registries`: after the loop, compute `counts` per source from `collection.entries`, load `history` from prior `registry_summary.json` `per_source`, and call `apply_source_floor`. Emit a `CrawlIssue` for any demoted source.

- [ ] **Step 4: Evidence manifest.** In `run_registry_update`, after computing `events`, write a plain-text manifest of the emitted events' supporting evidence:

```python
    manifest_lines = [f"# Registry evidence — {run_date}", ""]
    for e in events:
        manifest_lines.append(f"## {e['event_type']} — {e['identity']} ({e['confidence']})")
        manifest_lines.append(e["summary"])
        for ev in e.get("evidence", []):
            manifest_lines.append(f"- {ev.get('kind')}: {ev.get('value')} [{ev.get('confidence')}]")
        manifest_lines.append("")
    write_text(root / "data" / "current" / "registry_evidence.md", "\n".join(manifest_lines) + "\n")
```

- [ ] **Step 5: Run full suite → PASS. Commit**

```bash
git add mcp_newsletter/registries/__init__.py mcp_newsletter/updater.py tests/test_registry_collectors.py
git commit -m "feat(registries): parser-break floor and evidence manifest"
```

**Post-fix coverage:** parser-break floor (§7) ✓; evidence manifest (§9) ✓. All design sections now map to a task.

---

## As-Built Amendments

Reconciles the plan with what was implemented and reviewed. All divergences below are review-driven improvements or corrections of internal plan inconsistencies; the plan is amended here so it agrees with the code. Final state: **100 tests, all green.**

**Task 4 — shared classifier kept unpolluted.** The plan's Task 4 test (`description="Send and post messages"` → medium) could not pass against the unmodified `classify_catalog`. Resolved by a **registry-local** write-verb scan in `classify_registry_record` (imports `WRITE_RE`; bumps `unknown`/`low` → `medium` when a write verb appears in the description, appending a `registry_description` evidence row). `classifier.classify_catalog` is **unchanged**, so vendor-tier classification semantics are unaffected.

**Task 5 — added `run_discovery` tests.** Beyond the plan's `SelectTests`, added `RunDiscoveryTests` (records dates + tool confidence; swallows per-endpoint exceptions) and a second never-discovered identity-tiebreak case.

**Task 6 — `new_source` is seeding-gated.** To prevent a burst when a brand-new registry first comes online, `new_source` only counts added sources seeded on a PRIOR run (`meta.seeded_sources.get(s, run_date) < run_date`). The new_source test seeds the second source on an earlier date accordingly. Also added four negative tests (new server does not also emit new_source; liveness resets on reappear; delisted removed from state+liveness; source-down server carried forward with frozen liveness). Cleanups: dropped the unused `RANK` import and the vestigial `prev` param on `_event`; `last_discovered` is pruned on delist.

**Task 7/8 — per-host throttle wired (was a flagged to-do).** `throttle(urlparse(url).hostname)` is now called before every collector fetch (official, github_servers, docker incl. its per-server loop, pulsemcp, glama, smithery via `_fetch_with_auth`, mcpso). Snapshots are saved only for non-empty bodies (the `save_raw_text` call moved after the empty-body guard in the paginating collectors).

**Task 8 — collector robustness + smithery auth.** `docker` uses `item.get("name")` + skip and emits an issue on per-server YAML fetch failure; `glama` breaks on a repeating/stable cursor and on an empty page; `smithery` uses a self-contained `_fetch_with_auth` helper (the plan's flagged auth-header decision) that routes through `netguard.read_capped`/`max_response_bytes` and breaks on an empty page, and returns `[]`+issue when `MCP_NEWSLETTER_SMITHERY_KEY` is unset. The four `skip_network` tests assert an issue was recorded. Identity normalization: `merge.identity`/`_alias_keys` now lowercase `official_name` and `subpath`, closing a mixed-case dedup hole.

**Task 9 — reporting.** Event-field access uses `.get()` defensively; `DOUBLE_COUNT_NOTE` finalized to clean wording ("a server may also appear in the vendor-tier coverage above; the two tiers are counted independently"); the overflow test asserts the `registry_events.json` pointer.

**Task 10 — cold-start corrected (the plan's test was wrong).** The plan's Task 10 test returned the SAME server on both runs and expected the second to emit — which is only achievable by wiping the baseline, defeating cold-start and flooding on the second-ever run. As-built: `run_registry_update` persists the seeded baseline returned by `diff_and_events`. The test now verifies (a) first run is silent but state IS persisted, (b) a genuinely new server on a later run emits exactly one `new_write_server`, (c) an unchanged server stays silent across runs (no flood).

**Task 11 — floor compares raw-vs-raw.** `registry_summary.json` persists `per_source_raw` (raw collector counts) in addition to `per_source` (deduped, derived from `new_state` for consistency with `indexed`/`write_capable`); the parser-break floor reads `per_source_raw` as history so the >80%-drop check is like-for-like. A non-dict `per_source_raw` in a prior summary is guarded against.

**Outputs / config (doc reconciliation).** The run also writes intermediate `data/current/registry_section.md` and a distinct `_run/registry-manifest` snapshot (so it does not clobber the vendor `_run/manifest.json`); raw registry snapshot bundles under `data/snapshots/*/registries/` are gitignored.

**Accepted residual.** The `# VERIFY` parsers (pulsemcp/glama/smithery field names) are tested against **synthetic** fixtures; real-API field validation is the plan's stated §3 deferral, with the parser-break floor (`per_source_raw` history + `ABSOLUTE_FLOOR`) as the runtime backstop.

**Live-verified — official registry parser (no longer `# VERIFY`).** A live run revealed the real API wraps each record as `{"server": {...}, "_meta": {...}}`, carries status under `_meta["io.modelcontextprotocol.registry/official"].status`, and paginates via `metadata.nextCursor` (camelCase). The collector + fixture were corrected to this shape; a live pull now indexes real servers (≈112 unique from ≈210 version-rows; versions dedup by name) with write-capable detection and zero issues. The remaining `# VERIFY` parsers (pulsemcp/glama/smithery + the 6 vendor URLs) are still synthetic-fixture-tested pending the same live confirmation.
