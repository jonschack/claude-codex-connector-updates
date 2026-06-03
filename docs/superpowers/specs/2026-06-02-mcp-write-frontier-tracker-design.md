# Design: MCP Write-Frontier Tracker

- **Date:** 2026-06-02 (rev. 3 — multi-perspective improvement loop *converged* over 2 rounds: 6 adversarial reviews across alignment, feasibility, signal-quality, coverage, simplicity; all material findings resolved)
- **Status:** Draft — converged; pending operator review → per-phase implementation plans
- **Scope:** Keep the operator on the **absolute frontier of cutting-edge MCP capabilities, prioritizing WRITE-capable tools** (tools that take real actions). Make verified-write trustworthy, surface the newest + most *powerful* actions (not the most popular), catch new tools the moment they appear, and **push a weekly Write-Frontier digest + an always-current daily board + same-day alerts**.
- **Predecessors:** [2026-05-30 Registry & Vendor Sources](2026-05-30-ecosystem-registry-sources-design.md), [2026-06-01 Pipeline Hardening & Re-Aim](2026-06-01-pipeline-hardening-and-reaim-design.md) (capability layer, novelty, signals, Grok radar). This is the write-focused capstone.

## 1. Goal, Decisions & Non-Goals

### Goal
Be never more than a week behind the write-capable frontier (same-day on standouts), with an always-current ranked board in between — every item carrying its action class, evidence tier, and the exact prompt to use it.

### Locked decisions (from brainstorming)
- **Delivery:** **weekly digest + always-current daily board + same-day alerts** on standouts.
- **Scope:** **both, tiered** — curated surfaces (official registry, vendor connectors, Grok/X viral, news) drive the digest *headline*; registry-wide write-prioritized verification runs in the background.
- **Verification:** **remote `tools/list`, write-prioritized + scaled**, annotation capture, **plus a no-execution static `declared_manifest` tier** (review fix — see §4). **No sandboxed stdio execution.**
- **Build order:** **P1 verify → P2 push (digest) → P3 score → P4 recall** (reordered per review: ship the pushed digest before the scoring engine, so real output calibrates scoring).

### Grounding (accurate, measured 2026-06-02)
- 31,664 indexed servers; **only ~2,696 (8.5%) have a `remote_url`** → that is the live-`tools/list`-probeable universe (the other 91.5% are stdio/local). **~30,310 (95.7%) have a `repo_url`** → the static-manifest + GitHub-watch universe.
- Write evidence today: **40 `verified_tools`, 0 `annotation`, 5,538 `claimed_description`, 26,857 none.** The "0 annotation" is a *bug*, not absence (see §4 P1-0).

### The core gap
"Frontier of write-capable tools" = newest × most-powerful × **verified** actions. Today: verification is broken (0 annotations persisted), biased (remote-only excludes the powerful stdio tools), keyword-circular, and there's no proactive or always-current delivery.

### Out of scope (explicit)
- **Sandboxed stdio/local execution** (deferred; the `declared_manifest` static tier is the cheap mitigation instead).
- **Executing write actions** — we catalog/rank only, never invoke a tool's write.
- **Reddit / Discord / Product Hunt / ChatGPT-apps-directory / awesome-list diffs** as ingestion sources — declined for v1 (low marginal recall vs. cost/auth; HN + Grok + npm/PyPI + registry cover the same ground earlier). Documented decision, not oversight.
- **Replacing existing outputs** (write-capability report, LANDSCAPE_REPORT, capability feed) — additive only.

## 2. Design Principles
1. **Verified write is the spine, but verification must not be biased.** Headlines gate on observed evidence (`verified_tools`/`annotation`) **or** static `declared_manifest`; keyword `claimed_description` is a labeled "emerging" section. Report verified coverage **per action class**, never a flattering aggregate.
2. **Power and novelty outrank popularity.** The ranking is **lexicographic: evidence → action-power → recency**; momentum/virality is a hard-capped tiebreaker that can re-order *within* a power band but can never promote a low-power tool above a high-power one. **Engagement-only sources (Grok/X) may surface a candidate but never contribute to its score.**
3. **Don't trust what you can't probe — but don't ignore it either.** Static manifest parsing (no execution) lifts stdio tools above keyword-only without faking verification.
4. **Discovery must explore, not just exploit.** A reserved slice of the discovery budget probes unclassified/never-seen servers so the frontier can surface what the keyword classifier can't predict.
5. **One canonical identity everywhere.** A single normalizer reconciles registry / vendor / Grok / package sources; corroboration counts *distinct tiers after canonicalization*, never duplicate mentions.
6. **Extend, don't rewrite; additive; phased; never break the daily run.**

## 3. Target Module Layout (by phase)
```
mcp_newsletter/
  identity.py               # NEW [P1] single canonical repo/name normalizer (shared by all tiers)
  registry_classify.py      # FIX [P1] MERGE evidence (stop overwriting annotation/tool evidence)
  registry_discovery.py     # CHANGE [P1] write-priority + reserved exploration slice; persist annotations
  manifest.py               # NEW [P1] no-execution static tool-declaration parse (package.json/server.json/README)
  registries/base.py        # CHANGE [P1] RegistryServerRecord carries top-N write ToolRecords
  frontier_report.py        # NEW [P2] daily WRITE_FRONTIER_NOW board + weekly digest + teaching artifact
  action_power.py           # [P2] minimal keyword power-tier (high/med/low); [P3] refines per-tool (schema+confidence)
  frontier.py               # NEW [P3] lexicographic frontier rank + events; source-attested recency
  ingest/                   # NEW [P4]
    official_incremental.py #   updated_since cursor (additive-merge, no false delist)
    package_watch.py        #   npm search (keywords:mcp&sort=date) + PyPI newest RSS — unattended, pre-registry
    github_watch.py         #   release/star momentum — frontier candidates only, GraphQL batch
  signals.py                # CHANGE [P4] add HN Algolia + vendor changelog feeds
  registry_state.py         # CHANGE [P4] official_cursor + last_frontier_digest (idempotent weekly)
data/current/
  WRITE_FRONTIER_NOW.md + write_frontier_current.json   # always-current daily board
  WRITE_FRONTIER.md                                     # weekly digest (delta narrative)
  write_frontier.jsonl                                  # persistent frontier state
```

## 4. Phase 1 — Trust the write signal (verification foundation)

**P1-0 (bug-fix prerequisite): stop destroying annotation evidence.** In `run_registry_update`, discovery runs first and appends `mcp_annotation` evidence to each record, then `classify_registry_record` runs and **overwrites** it with a bare `rec.evidence = evidence` (catalog-only) assignment — wiping the annotations. Confirmed against current code + state: **0 of 31,664 records carry annotation evidence.** Fix: change that assignment to a **union-merge** that preserves all `mcp_annotation`/`tool_text` evidence kinds and adds catalog evidence under a stable dedup key. Add an **integration test** running discovery → classify in order, asserting the annotation survives and yields a headline-gateable tier. *Without this, P2–P4 build on sand.* (Line numbers omitted deliberately — they rot; the bug is the discovery-append-then-classify-overwrite ordering.)

| Workstream | Design |
| --- | --- |
| **Per-tool storage on registry records** | `RegistryServerRecord` today holds no tools (base.py) — but P2/P3 need per-tool action class + example prompt. Add a bounded `tools: List[ToolRecord]` (top-N **write** tools only, to cap size) + jsonl (de)serialization. Vendor `capability.py`/`novelty.py` then work on both record types. |
| **Write-priority + exploration** | Replace round-robin `select_discovery_candidates` with priority buckets: **(1) new since last run** (from P4 incremental cursor — top priority, reserved slots), (2) source-authority (official/vendor), (3) claimed-write (keyword) as a *boost not a gate*, **(4) reserved ε-slice (~20%) for unclassified/`none`-tier/never-probed remote servers** so discovery samples outside the keyword prior, **(5) a reserved re-verification slice for headline tools past their `verified_at` decay** (§8) so freshness re-checks don't starve new-tool discovery. Deterministic + rotating. |
| **Annotation capture (persisted)** | Persist `destructiveHint`/`readOnlyHint`/`idempotentHint`/`openWorldHint`; `readOnlyHint=false`/`destructiveHint=true` = `annotation`-tier write evidence; `destructive`+`openWorld` flags the highest-blast-radius actions (feeds power in P3). |
| **`declared_manifest` static tier** (`manifest.py`) | For stdio servers (the 91.5% with no remote_url) parse the repo's published `package.json`/`server.json`/README **tool declarations** (names + descriptions + input schemas are often static) — **no execution**. New evidence tier `declared_manifest`, ranked between `claimed_description` and `annotation`. Narrows the stdio blind spot where the most powerful local writes live. **Bounded to the same cap-bounded/rotating candidate set as discovery (never all ~30k repos)** — reuses `select_discovery_candidates`' eligibility + cadence. |
| **Per-action-class coverage telemetry** | Report verified/declared/claimed counts **per action class** (so "0% of system_control verified" is visible), not just an aggregate verified count. |

**Done when:** annotations survive end-to-end (integration test green); the discovery ε-slice converts some non-keyword servers to verified (proving the prior is leaky); `declared_manifest` lifts stdio servers; coverage is reported per action class.

## 5. Phase 2 — Push it (digest + always-current board + alerts) — *ships before scoring*

**Goal:** get the pushed, prompt-ready frontier into the operator's hands now, ranked by a simple, defensible key (no full score yet).

- **`frontier_report.py`** renders, every **daily** run, **`WRITE_FRONTIER_NOW.md` + `write_frontier_current.json`** — the always-current ranked board (the scoring already runs daily; don't withhold it for a week). Ranking key (P2-lite): **(evidence_tier, action_power_tier, recency desc)**. P2 ships a **minimal keyword-derived power tier** (high/med/low from the existing `WRITE_TAGS`/`WRITE_TERMS` in the classifier); P3 (§6) refines it per-tool with schema+confidence and swaps in the full score. No momentum yet. Sections: **Verified/Declared headline** vs **Emerging (claimed)** vs **Viral (Grok)**.
- **Weekly `WRITE_FRONTIER.md`** = the *delta narrative* layered on the board ("new / newly-verified / risen since last week"), emailed via `emailer.send_daily_report`. **Idempotent weekly cadence:** gate on persisted `last_frontier_digest` (emit when `run_date - last ≥ 7`, then stamp) so a missed/repeated cron day doesn't skip/double-send.
- **Same-day alerts (two triggers):** (a) the existing high bar, **plus (b) a lower bar: any newly-discovered `high`-power verified/declared write tool, regardless of vendor fame or virality** (review fix — power+novelty alerts even when obscure).
- **Grok radar freshness contract:** the Viral section prints the radar's `last_run` age; if older than the digest window it degrades **loudly** ("radar stale (N days) — viral coverage incomplete") and emits a `CrawlIssue` nudging a sweep *before* the weekly fires.
- **Meetup teaching artifact:** also emit a **prompt-first, action-class-grouped** rendering ("What You Can Now Ask Your AI To Do — Write Edition") and draft it into the predecessor's `meetup-hormozi` lead-magnet path (human-approved; no auto-publish). Serves the second stated use.

**Done when:** a daily board + weekly email + standout alerts ship; the meetup teaching draft is produced; Grok staleness is loud.

## 6. Phase 3 — Score & classify properly (replaces P2-lite sort key)

- **`action_power.py` — per-TOOL, ordinal, 3 tiers.** Classify each *write tool* (not server) into **`high`** (money/comms/deploy/system-control), **`medium`** (data-write/social/physical), **`low/none`**, from name + description + **schema/annotations** (preferred over keywords). A server's power = **max over its verified write tools** (power = most dangerous thing it can do). `destructive`+`openWorld` annotations bump within-tier. Each classification carries a **confidence** (schema/annotation-derived = high; keyword-only = low). (Fine-grained 7-class labels deferred until calibrated.)
- **`frontier.py` — lexicographic, popularity-capped.** Evidence ordering uses one explicit `EVIDENCE_TIER_RANK` map (`verified_tools` > `annotation` > `declared_manifest` > `claimed_description` > `none`) so the comparison and the "`declared_manifest` ranks between claimed and annotation" rule live in one place. Rank by **(evidence_tier → action_power_tier → recency)** dominant; a single **bounded attention factor** (≤~15%, collapsing momentum+corroboration so they're not triple-counted) only re-orders within a band. **Engagement-only sources excluded from the score.** **Classification confidence damps** the score (low-confidence can't reach the headline). Golden-file test asserts a low-power viral item never outranks a high-power new one, and that the top-decile has discriminating spread.
- **Source-attested recency.** Derive recency from **published/updated/first-release timestamps** (official registry, GitHub), `first_write_seen` only as flagged fallback. **Suppress recency credit for servers whose registry `first_seen` predates the tracker** so the P1 claimed→verified backfill doesn't flood digests with stale tools masquerading as new.
- **Events:** merge `new_write_tool`+`write_verified` into one `write_verified{first_seen flag}`; keep `frontier_capability` (score threshold). Flood-capped (reuse `notable_source` aggregate).

**Done when:** ranking is power/novelty-dominant (tested against rank-inversion), tool-level + confidence-aware, with attested recency; the board/digest swap to the real score.

## 7. Phase 4 — Catch new instantly + widen recall

- **`ingest/official_incremental.py`:** official registry **`updated_since` cursor** (verified to exist: supports `updated_since`+`cursor`+`limit≤100`). **Additive-merge only** — incremental absence is NOT a delist (full liveness/delisting stays on the periodic full pull); honor `status=deleted` tombstones as the only incremental delete.
- **`ingest/package_watch.py`:** poll **npm search (`registry.npmjs.org/-/v1/search?text=keywords:mcp&sort=date`, with `limit` + 429 backoff — the legacy `replicate.npmjs.com/_changes` feed was deprecated 2025-05-29) + PyPI newest RSS** filtered to MCP packages — unattended, and sees a new TS/Python server *before* any registry. New package → `claimed` candidate + repo cross-link → momentum/corroboration.
- **`ingest/github_watch.py`:** release/star deltas **for frontier candidates only** (verified-write + write-priority top-N — NOT all 30k repos), via **GraphQL batch (100 repos/call)** to stay in rate limits. Degrade to no-momentum on limit, never crash.
- **`signals.py`:** add **HN Algolia** (free, keyword-queryable) + vendor changelog feeds.
- **Fusion via `identity.py`:** all tiers cross-link on the single canonical normalizer; corroboration = distinct tiers after canonicalization (engagement-only excluded). Test that `repo.git` / `repo/tree/main` / `www.` variants collapse to one row with corroboration = N tiers.

**Done when:** a newly-published registry/npm/PyPI write server surfaces next run; github momentum tracks only candidates; fusion dedups variants correctly.

## 8. Data Model, State, Config, Testing, Risks, Metrics

**Model/state:** `RegistryServerRecord.tools` (bounded write tools); evidence tiers gain `declared_manifest`; per-tool `action_class`/`action_power`/`confidence`; `frontier_score`+`first_write_seen`+`verified_at`; `write_frontier.jsonl`; `registry_meta` gains `official_cursor`, github star snapshots, `last_frontier_digest`. **Verified-evidence freshness:** `verified_at` + re-verification cadence (the reserved discovery slice, §4 bucket 5); decay/flag evidence older than **8 weeks (default; tunable)** so the digest reflects *current* behavior.

**Config (minimal per YAGNI review):** hardcode constants; expose **only** `MCP_NEWSLETTER_DISCOVERY_CAP` (cost lever) and `MCP_NEWSLETTER_FRONTIER_ALERT_THRESHOLD` (noise lever) as env. Promote weight vectors to env only when calibration demands.

**Testing:** TDD the pure pieces (identity normalizer incl. variant-collapse; manifest parse; action_power per tier incl. multi-action max + confidence; lexicographic frontier rank incl. rank-inversion + top-decile spread; recency backfill-suppression; weekly idempotency). Integration test for the **P1-0 annotation-merge fix**. Fixtures for incremental/package/github/HN parsers. Scheduled live-contract (non-blocking) for `updated_since` + a remote `tools/list` sample. No regressions to the daily run/reports.

**Risks:** discovery cost (real probeable pond is ~2.7k, not 31k — size the cap to that); github_watch must never iterate all repos (candidates-only + GraphQL); stdio still partly opaque (declared_manifest mitigates, doesn't solve — labeled honestly); action-power fuzzy (ordinal tiers + confidence + schema-preference); weekly latency (daily board + same-day alerts cover it); ranking gaming (power/novelty-dominant, engagement excluded from score).

**Success metrics:** (1) verified+declared write coverage climbs, **reported per action class**; (2) **frontier-recall metric** — reconcile each week's surfaced write tools against an *external, capability-based* ground-truth set (hand-labeled / vendor release notes — **not** the Grok set used for calibration, to avoid circularity) and track **miss count + median surfacing latency**; (3) time-to-surface a new high-power write ≤ 1 run to discover, ≤ 1 day to alert; (4) every item ships `{action tier, evidence tier, confidence, example prompt, attested recency}`.

## 9. Sequencing & Operational Note
**P1 (verify, incl. the annotation-merge bug-fix) → P2 (push the digest/board) → P3 (real scoring) → P4 (catch-new + recall).** Each phase → its own `writing-plans` plan, TDD'd + reviewed (pipeline-hardening cadence). Discovery/ingestion runtime lands on the daily job (Eastern-time box); the weekly digest is gated on persisted state; alerts ride the daily run; the Grok radar stays operator-run and is fused (with a loud staleness contract) when fresh.
