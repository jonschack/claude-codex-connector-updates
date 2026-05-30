# Design: Ecosystem Registry & Vendor Sources

- **Date:** 2026-05-30
- **Status:** Approved (design); pending implementation plan
- **Scope:** Add ecosystem-wide MCP registries and additional first-party vendor
  catalogs as collection sources, tracked as a distinct tier alongside the
  existing four vendor catalogs.

## 1. Goal & Non-Goals

### Goal
Expand the daily write-capability tracker beyond the four first-party catalogs
(claude/codex/gemini/grok) to cover the broader MCP ecosystem, so newly
write-capable servers are detected wherever they first appear.

### In scope
- **Registry tier (7 sources):** official MCP Registry, GitHub
  `modelcontextprotocol/servers`, Docker MCP Catalog (`docker/mcp-registry`),
  PulseMCP, Smithery, Glama, mcp.so.
- **Vendor tier (6 new sources):** OpenAI/ChatGPT connectors, Cursor
  (`cursor.directory/mcp`), VS Code / Copilot MCP gallery, Cline
  (`cline/mcp-marketplace`), Continue (`hub.continue.dev`), Cloudflare remote
  MCP server list.

### Out of scope (explicit)
- **Tier 3 aggregators** (Composio, Pipedream, Zapier): per-user-authenticated,
  emit thousands of near-identical write actions, no anonymous `tools/list`.
  Dropped by decision.
- **Incremental fetch** (e.g. official-registry `updated_since` cursor):
  deferred to a later phase; v1 does complete, cap-bounded pulls everywhere.
- **Retroactive cleanup of the existing 378 MB vendor snapshot history:**
  strongly recommended as a separate companion task; not part of this feature.
- Changing the vendor tier's existing committed binary `state.sqlite`.

## 2. Two-Tier Architecture

The system keeps two cleanly separated tiers that share the low-level
utilities (`fetch_text`, `mcp_discovery`, `classifier`, hashing):

- **Vendor tier** — the existing per-`provider` pipeline. The 6 new vendor
  collectors plug into `collect_all` → `_dedupe_servers` → `classify_all` →
  `state.upsert_*` → report with **no change to the existing server/tool
  record shape or report structure**; they are simply new `provider` values.
  (The only additive change is a lightweight per-provider baseline marker for
  cold-start seeding, §7.)
- **Registry tier** — a new parallel subsystem with its own identity model,
  state, diff, and report section. One server seen in many registries collapses
  to a single canonical entry carrying a list of `sources`.

### Module layout
```
mcp_newsletter/
  providers/                       # VENDOR TIER (existing shape)
    claude.py codex.py gemini.py grok.py            # existing
    openai.py cursor.py vscode.py cline.py continue_.py cloudflare.py  # NEW
  registries/                      # REGISTRY TIER (new subsystem)
    __init__.py    # collect_all_registries(): try/except per source
    base.py        # RegistrySource interface + RegistryServerRecord
    merge.py       # identity resolution + history-preserving dedup/merge
    official.py github_servers.py docker.py
    pulsemcp.py smithery.py glama.py mcpso.py
  registry_state.py                # JSONL state load/diff + event emission
  registry_reporting.py            # "Ecosystem Registries" report section
```
Each collector is one focused file. A failing source becomes a `CrawlIssue`
and never breaks the run (existing convention,
`providers/__init__.py`).

## 3. Per-Source Collectors

Each source prefers a structured API, falls back to scrape, degrades to a
`CrawlIssue`. All endpoints, keys, and caps are env-overridable.

### Registry tier
| Source | Access | Notes / risk |
| --- | --- | --- |
| Official MCP Registry | REST `GET /v0.1/servers` (paginated, no auth) | Canonical. Full pull in v1; cap set high enough to capture all. Provides `repo`, `remotes[].url`, `packages`, `status`. Filter `status=deleted` → delist. |
| GitHub `modelcontextprotocol/servers` | Fetch README via raw GitHub, parse list | Overlaps official; dedup absorbs it. |
| Docker MCP Catalog | Read `docker/mcp-registry` YAML via GitHub raw/API | ~200 verified; avoids scraping hub.docker.com. |
| PulseMCP | Public API, paginated | Has popularity/traffic signal. **Verify exact contract at implementation.** |
| Glama | API, paginated | Largest volume; GitHub-indexed → reliable repo URLs. **Verify contract.** |
| Smithery | Registry API — **may need key** | If `MCP_NEWSLETTER_SMITHERY_KEY` absent → skip with info-level issue (not a failure). **Verify contract.** |
| mcp.so | HTML scrape (no documented API) | Most fragile; isolated; lowest priority. |

### Vendor tier (route through existing pipeline)
| Provider | Source | Access |
| --- | --- | --- |
| `openai` | ChatGPT/Apps connector directory | scrape |
| `cursor` | `cursor.directory/mcp` | scrape |
| `vscode` | Copilot/VS Code MCP gallery (GitHub-hosted list) | API/raw JSON |
| `cline` | `cline/mcp-marketplace` repo | raw JSON |
| `continue` | `hub.continue.dev` MCP blocks | API/scrape |
| `cloudflare` | Cloudflare docs "remote MCP servers" list | scrape; many http(s) → live discovery applies |

### Pagination, caps, per-page isolation
- Each registry source pages until exhausted **or** a per-source `max_servers`
  / `max_pages` cap; hitting a cap logs a truncation `CrawlIssue` (no silent
  caps).
- **Per-page** try/except: one bad page logs an issue; partial results still
  flow.
- A soft per-run **time budget** bounds total wall-clock; exceeding it stops
  further pagination and logs what was skipped.

## 4. Identity, Dedup & Merge (registry tier)

### Identity resolution (in order)
1. **Official-registry canonical name** (reverse-DNS, e.g.
   `io.github.owner/server`) when present.
2. **`repo_url#subpath`** — subpath from the package/source dir (default repo
   root). Handles monorepos: many servers under one repo stay distinct.
3. **`<source>:<slug(name)>`** — last resort so an unmatched entry still
   records.

Bare `repo_url` is **never** a key (would collapse monorepos).

### Alias table & stability
- `registry_aliases` maps every observed **high-specificity** key (canonical
  name, `repo#subpath`) → canonical identity. **`remote_url` is never an alias
  key** (shared gateways host many distinct servers).
- A record matching any existing alias reuses that identity (gaining a stronger
  identifier remaps, never orphans).
- When a new record bridges two existing canonical entries, the
  lowest-sorting identity wins; the merge **preserves `min(first_seen)`** and
  unions aliases, and is logged as a `CrawlIssue` (not a first-class report
  event — collisions are rare with high-specificity keys).

### Canonical record (`RegistryServerRecord`)
`identity`, `name`, `description` (longest non-empty wins), `repo_url`,
`remote_url` (first http(s)), `sources: [{source, source_url, source_id, tags,
last_updated}]`, merged `capabilities`/`tags`, and post-classification
`write_confidence` + `evidence` (with per-evidence-source detail, §6).

## 5. Live Discovery & Safety (shared `mcp_discovery`)

Hardening applies to **both** tiers (vendor tier benefits too).

- **SSRF guard:** before any discovery POST, require http(s) scheme and reject
  loopback / private / link-local / metadata ranges (e.g. 169.254.169.254).
  Env allowlist override. v1 blocks literals + ranges; full DNS-rebinding
  IP-pinning is a documented residual risk deferred to a later phase.
- **Response size cap:** `_post_json` and `fetch_text` read at most
  `MAX_RESPONSE_BYTES` (default 5 MB) and abort beyond it.
- **Politeness:** retry with exponential backoff + jitter, honor `429` /
  `Retry-After`, capped retries, per-host min-interval throttle.

### Registry discovery selection (deterministic, capped)
- Candidates = records with an http(s) `remote_url`.
- Sort `(never_discovered desc, last_updated desc, identity asc)`; take first N
  (`MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP`, default 150).
- Persist `last_discovered` per identity; re-discover on a cadence K (default a
  few days) so the set **rotates predictably** rather than flapping.
- Concurrency: bounded thread pool (default 8 workers). Workers **only
  fetch/parse and return `ToolRecord`s** — all SQLite/state writes and
  `add_issue` calls happen on the main thread after the pool joins (SQLite and
  `CollectContext` are not thread-safe).

## 6. Classification

Reuses `classifier.py` unchanged (`unknown<low<medium<high`,
`REPORTABLE={medium,high}`). Per registry server, strongest evidence wins:
1. **Live `tools/list`** (only for the capped/discovered remote set) → tool
   schemas + `destructiveHint`/`readOnlyHint` → strongest signal.
2. **Registry tags/categories** → a thin **tag-normalizer** maps known
   write-implying tags (Docker categories, Glama tags) into `capabilities`
   before `classify_catalog`, keeping the shared classifier unpolluted.
3. **Name/description text** → existing verb regex.

### Per-evidence-source confidence + TTL
- Persist confidence **per evidence source** (tools vs catalog) with a
  timestamp.
- Effective confidence = max over **non-stale** sources. Tool-evidence TTL ≥
  discovery cadence K, so a server is never "stale" before its scheduled
  re-discovery.
- This prevents false regressions when a server falls outside the discovery
  cap (absent tool evidence that run must not drop its confidence).

## 7. State, Diff & Events (registry tier)

### Canonical committed state — sorted JSONL
- Authoritative diff state lives in **`data/current/registry_state.jsonl`**,
  one server-record per line, **sorted by identity**.
- Rationale: a single sorted text file git-delta-compresses to a tiny daily
  diff (empirically, the analogous `servers.json` diffs ~360 lines/day), it is
  human-diffable in PRs, and line-oriented JSONL minimizes add/remove diffs.
- **No committed binary for the registry tier.** An optional local SQLite cache
  is rebuildable and never the source of truth.

### Events
Emitted against the **canonical (deduped) server**, so a status change fires
once, not per-registry. Event query ordered by `(event_type, identity)` for
deterministic, low-churn output.
- `new_write_server` — first write-capable sighting (after baseline exists).
- `write_status_changed` — unknown/low → medium/high.
- `write_status_regressed` — medium/high → low/unknown, **only on fresh
  like-for-like evidence** (never merely because we didn't re-discover).
- `delisted` — not seen in **any successful source** for N consecutive runs
  (default 3, env-tunable); official-registry `status=deleted` → immediate.
- `new_source` — existing write-capable server appears in an additional
  registry; **summarized as a count**, not table rows.

### Liveness correctness
- A server's liveness only decrements when **the source carrying it succeeded
  this run**. A source that errored (`CrawlIssue`) **freezes** its servers'
  counters — prevents false delists when a source is down.
- Because v1 does complete pulls everywhere, every source returns a full
  listing, so liveness is uniform across sources.

### Cold-start seeding
- The **first run per source** records `first_seen` silently (no events);
  alerts fire only for servers appearing after a source's baseline exists
  (`registry_meta.seeded_at` gates this).
- The same silent baseline-seed extends to the **6 new vendor providers** on
  their first appearance (gated by an additive per-provider `seeded_at` marker),
  so they don't dump a one-time wall of alerts.

### Parser-break detection
- Per-source **expected-minimum floor**: if a source historically returned ≫X
  and now returns ≈0, emit a warning `CrawlIssue` and treat the source as
  **failed** (frozen liveness), not legitimately empty. Run 1 (no history) uses
  a configured absolute minimum for known-large sources (e.g. official
  registry > 100).

### Atomic metadata
All run metadata (`seeded_at`, liveness counters, `last_discovered`) commits
atomically with the run's recorded data; a crash never leaves them out of sync.

## 8. Reporting

`registry_reporting.py` adds an **"Ecosystem Registries"** section, kept
distinct from the existing per-vendor "Coverage" (vendor report unchanged):
- Deduped indexed-server count, write-capable count, new-write-capable-today.
- Per-registry counts (which sum higher than the deduped total — explicitly
  noted).
- New/changed/delisted/regressed write-capable servers table, **row-capped**
  (mirroring the existing 25-issue cap) with an overflow pointer to JSON.
- `new_source` as a count line.
- An explicit note that a server may be counted in **both** the vendor tier and
  the registry tier.
- Enabled/disabled source set (and why each is off) surfaced in
  `data/current/registry_summary.json` and logged at run start.

## 9. Storage, Snapshots & Git

- **Committed (text, git-deltas well):** `registry_state.jsonl`,
  `registry_events.json`, `registry_summary.json`, and a **plain-text evidence
  manifest** (source hashes, counts, and the raw excerpts backing each emitted
  event — preserves auditability per the project's evidence principle).
- **Gitignored (local-only):** raw per-page response bundles (gzipped on disk).
  The file-count cost — not git-history size — is the reason; text history is
  cheap (378 MB working tree → ~10 MB `.git`). The evidence manifest stays
  **un-gzipped** so git can delta it.
- `gitops.py` commit path list updated to add the specific registry text
  outputs and exclude raw bundles (currently it adds `data/` wholesale).

## 10. Configuration

- Master allowlist `MCP_NEWSLETTER_REGISTRIES` (default: all enabled).
- Per-source `MCP_NEWSLETTER_<SOURCE>_URL`, `_KEY`, `_MAX`.
- `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP` (default 150), discovery cadence K,
  delist threshold N, `MAX_RESPONSE_BYTES` (default 5 MB), per-host throttle
  interval, soft time budget.
- First run is a heavy-but-silent baseline seed; steady state is incremental in
  effect (caps + rotation). Documented so the first run's size/runtime is
  expected.

## 11. Testing (offline `unittest`)

Per-invariant tests, all using saved snapshot fixtures (no network):
- One parser fixture test per source (13).
- SSRF blocklist rejects private/loopback/metadata IPs; size cap aborts an
  oversized body.
- Monorepo: two servers under one repo → two entries.
- Alias remap: gaining a `repo_url` reuses identity, fires no new event.
- Cold-start: first run seeds silently (zero events).
- Delist after N runs — but **not** when the carrying source failed.
- Regression suppressed on evidence-source switch (tools→absent→catalog).
- Discovery selection deterministic and rotates over runs.
- Parser-break floor: historical-≫X → ≈0 emits a warning and freezes liveness.
- End-to-end registry update with `skip_network` (mirrors `test_update.py`).

## 12. Operational Note
The added runtime (pagination + capped concurrent discovery) lands on the
daily job, which runs on the Eastern-time machine. This Mac's local cron still
can't push and lacks the Codex plugin path — pre-existing, out of scope here.

## Appendix: Resolved Review Findings
Eight adversarial review rounds converged the design; net effect was *smaller
and safer*. Key resolutions folded in: two-tier model; monorepo-safe identity
with high-specificity alias table; deterministic rotating discovery cap;
SSRF + response-size hardening; per-evidence-source confidence with TTL;
source-down-aware liveness; cold-start silent seeding (both tiers);
parser-break floor; sorted-JSONL committed state (no registry binary);
deterministic event ordering. Dropped as YAGNI/over-engineering: incremental
`updated_since` fetch, DNS-rebinding IP-pinning, heavy `merged` audit events.
Corrected premise: text snapshots do **not** bloat git history (the real cost
is working-tree file count), so raw bundles are gitignored while consolidated
text state is committed.
