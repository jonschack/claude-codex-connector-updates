# Design: MCP Write-Frontier Tracker

- **Date:** 2026-06-02
- **Status:** Draft — pending review & per-phase implementation plans
- **Scope:** Keep the operator on the **absolute frontier of cutting-edge MCP capabilities, prioritizing WRITE-capable tools** (tools that take real actions). Turn the pipeline from "broad but shallow" into a system that (1) *verifies* write-capability, (2) scores how new/powerful each write tool is, (3) catches new ones the moment they appear, and (4) **pushes a weekly Write-Frontier digest + alerts**.
- **Predecessors:** Builds on [2026-05-30 Ecosystem Registry & Vendor Sources](2026-05-30-ecosystem-registry-sources-design.md) and [2026-06-01 Pipeline Hardening & Re-Aim](2026-06-01-pipeline-hardening-and-reaim-design.md) (capability layer, novelty, signals, Grok radar). This spec is the write-focused capstone.

## 1. Goal, Decisions & Non-Goals

### Goal
A weekly, push-delivered view of the newest, most powerful, **verified** write-capable MCP tools — so the operator is never more than a week behind the frontier (and same-day on standouts), with the exact prompt to use each one.

### Locked decisions (from brainstorming)
- **Delivery:** **weekly digest** (push email + committed report) **+ same-day alerts** on standouts.
- **Scope:** **both, tiered** — curated high-signal surfaces (official registry, vendor connectors, Grok/X viral, news/changelogs) drive the digest *headline*; **registry-wide write-prioritized verification runs in the background** to surface hidden gems.
- **Verification:** **remote `tools/list`, write-prioritized + scaled**, plus annotation capture. **No sandboxed stdio execution** (deferred — see Non-Goals).
- **Build:** full spec → per-phase implementation plans (P1→P4), each TDD'd and reviewed.

### The core gap this closes
"Frontier of write-capable tools" = the intersection of four things the system is weak on today: **verified write** (only 40 of 5,538 are `verified_tools`; the rest are description keyword-matches), **recency** (no write-specific novelty), **action power** (no money/comms/deploy ranking), and **proactive delivery** (everything is pull).

### Out of scope (explicit)
- **Sandboxed stdio/local execution** — the majority of registry servers are stdio with no remote URL and stay unverifiable; the digest labels them "emerging/claimed", never "verified". Deferred (needs Docker/Podman; large lift).
- **Autonomous actions** — we only *catalog and rank* write tools; we never execute their write actions.
- **Replacing existing outputs** — the write-capability report, LANDSCAPE_REPORT, and capability feed remain; the Write-Frontier digest is a new, parallel output.
- **Non-English tool/desc NLP** — action-power classification is English-keyword + schema-based; non-EN stays low-confidence (pre-existing limitation).

## 2. Design Principles
1. **Verified write is the spine.** Headlines cite only `verified_tools`/`annotation` evidence; `claimed_description` is a clearly-labeled "emerging" section, never presented as confirmed.
2. **Extend, don't rewrite.** Reuse `registry_discovery`, `classifier`, `novelty`, `signals`, `capability`, `emailer`, evidence tiers, `CrawlIssue`, env config. New logic lives in small, focused modules.
3. **Tiered fusion.** One ranked frontier view fuses registry + vendor + Grok radar + news/GitHub, deduped, with a cross-source corroboration boost.
4. **Weekly cadence, same-day alerts.** Routine items wait for the weekly digest; standouts page immediately.
5. **Transparent, tunable scoring.** The Write-Frontier score is component-summed and env-weighted; nothing is a black box.
6. **Never break the daily run.** Additive, env-gated, phased.

## 3. Target Module Layout (additions by phase)
```
mcp_newsletter/
  registry_discovery.py     # CHANGE [P1] write-prioritized candidate selection; capture annotations
  registry_classify.py      # CHANGE [P1] promote claimed->annotation/verified when tools/annotations observed
  action_power.py           # NEW [P2] classify a write tool's action class + power weight
  frontier.py               # NEW [P2] frontier_score + frontier events (new_write_tool, write_verified, frontier_capability)
  ingest/                   # NEW [P3] incremental "what's new" sources
    official_incremental.py #   official MCP registry updated_since cursor
    github_watch.py         #   release/star deltas for repos the registry already tracks
  signals.py                # CHANGE [P3] add vendor changelog feeds
  frontier_report.py        # NEW [P4] weekly Write-Frontier digest (fusion + ranking + example prompts)
  cli.py / updater.py       # CHANGE [P4] `frontier` command + weekly cadence + alert wiring
data/current/
  write_frontier.jsonl      # NEW persistent frontier state (scores, first_write_seen, momentum)
  WRITE_FRONTIER.md         # NEW the weekly digest artifact
```

## 4. Phase 1 — Trust the write signal (verification foundation)

**Goal:** grow `verified_tools`/`annotation` write coverage fast, *where it matters* — so the frontier rests on observed behavior, not keywords.

| Workstream | Design |
| --- | --- |
| **Write-prioritized discovery** | Replace the round-robin discovery selection (`registry_discovery.select_discovery_candidates`) with a `write_priority(record)` ranker: prioritize records that are (a) **claimed write** (classifier said medium/high from description/tags), (b) **never-discovered or new** (`first_seen` recent / no tool evidence), (c) **high source-authority** (official/vendor > community). Take the top-N by priority (cap raised, env-tunable), so each run converts the highest-value *claimed* writes into *verified*. Still deterministic + rotating to avoid flapping. |
| **Annotation capture** | Persist tool MCP annotations (`destructiveHint`, `readOnlyHint`, `idempotentHint`, `openWorldHint`) on the discovered `ToolRecord`/server record. `readOnlyHint=false`/`destructiveHint=true` is **direct write evidence** (tier `annotation`), stronger than keywords. |
| **Tier promotion** | In `registry_classify`, when a server gains observed tools/annotations, promote its evidence from `claimed_description` → `annotation`/`verified_tools` and record the transition (feeds the `write_verified` event in P2). |
| **Coverage telemetry** | Track and report verified-write coverage over time (e.g. `verified_write_count` in the landscape/summary), so we can see the 40 → hundreds climb. |

**Done when:** a run measurably converts claimed→verified writes (target: verified-write count climbs run-over-run), annotations are persisted, and discovery demonstrably targets write-likely servers first.

## 5. Phase 2 — Score the frontier (action power + events)

**Goal:** rank write tools by *how new and how powerful* their action is.

- **`action_power.py`** — classify each write tool into an **action class** from name/description/annotations: `money` (trade/pay/transfer), `comms` (send/email/message/call), `deploy` (deploy/release/provision), `data_write` (create/update/delete records), `system_control` (run/exec/control device/browser), `social` (post/publish), `physical` (IoT/robot), else `other`. Each class carries a tunable **power weight** (e.g. money/comms/deploy/system highest). Transparent keyword+schema rules; confidence flagged.
- **`frontier.py`** — `frontier_score(record, seen_before, run_date, weights)` = weighted sum of: **verified_write tier** (verified > annotation ≫ claimed), **recency** (first_write_seen within window), **action_power**, **momentum** (stars/likes rising — from P3), **source_authority**, **corroboration** (number of independent sources). Bounded [0,1], component breakdown logged.
- **Frontier events** (first-class, write-focused — distinct from objective-(a) write deltas): `new_write_tool` (a verified write tool seen first time), `write_verified` (claimed→verified transition from P1), `frontier_capability` (score ≥ threshold). Flood-capped per source (reuse the `notable_source` aggregate pattern from novelty.py).

**Done when:** every write tool has an action class + frontier score; the three frontier events fire deterministically and are unit-tested.

## 6. Phase 3 — Catch new instantly (incremental ingestion)

**Goal:** minimize time-to-surface for a brand-new write tool.

- **`ingest/official_incremental.py`** — use the official MCP registry's `updated_since` cursor (deferred in the predecessor spec) to fetch only **new/changed** servers each run; persist the cursor in `registry_meta`. This is the cleanest "what's new" feed and the frontier's backbone.
- **`ingest/github_watch.py`** — for servers with a GitHub `repo_url` (the registry stores these), fetch latest **release** + **star count** via `gh`/API; detect new releases and star spikes → **momentum** signal feeding the frontier score. Cache star snapshots in state; respect rate limits (gh auth + cap per run).
- **`signals.py`** — add a few **vendor changelog/release feeds** (Anthropic connectors, OpenAI, MCP blog already present) so announcements of new write connectors are caught and cross-linked.
- **Cross-link** ingested signals to registry/vendor records by repo_url/name → drives the corroboration boost.

**Done when:** a newly-published official-registry write server appears in the next run (not a full re-pull), and star/release momentum is captured for tracked repos.

## 7. Phase 4 — Push the frontier (weekly digest + alerts + fusion)

**Goal:** the operator is pushed the frontier, ranked and prompt-ready.

- **`frontier_report.py`** — render **`WRITE_FRONTIER.md`**, the weekly digest:
  - **Headline section (verified):** top new/rising **verified** write tools by frontier score, grouped by action class, each with `{tool, action class, what it does, example prompt, source, first_seen, evidence tier, corroboration}`.
  - **Emerging section (claimed):** high-momentum but unverified writes, clearly labeled "claimed / not yet verified."
  - **Viral section:** the Grok/X radar's top write-capable items (engagement-ranked), fused + deduped against the above.
- **Fusion + corroboration** — merge frontier candidates from registry + vendor + Grok radar + news; dedup (by repo_url/normalized name — fixing the URL-variant edge from the radar); boost score by independent-source count.
- **Delivery** — a `frontier` CLI command renders the digest; **weekly cadence** (env: run on a chosen weekday, or `frontier --weekly`); `emailer.send_alert`/`send_daily_report` ships it. **Same-day alerts**: when a `frontier_capability` clears a high bar (e.g. major-vendor new verified write, or a viral write tool), fire an alert on the *daily* run regardless of the weekly digest.
- Persist `write_frontier.jsonl` (scores, first_write_seen, momentum) for week-over-week dedup/rising.

**Done when:** `WRITE_FRONTIER.md` generates a ranked, grouped, prompt-ready digest; weekly email + standout alerts wire through the existing emailer; the Grok radar is fused in.

## 8. Data Model, State & Config
- **Additive fields:** tool/server records gain `annotations` (P1, ToolRecord already has it), `action_class` + `action_power` (P2), `frontier_score` + `first_write_seen` (P2), `momentum` (P3, stars/likes).
- **New events:** `new_write_tool`, `write_verified`, `frontier_capability`.
- **New state:** `write_frontier.jsonl` (frontier dedup/rising, like the Grok radar state); `registry_meta` gains `official_cursor` + GitHub star snapshots.
- **Config (env):** `MCP_NEWSLETTER_DISCOVERY_CAP` (raised), `..._WRITE_PRIORITY_WEIGHTS`, `..._ACTION_POWER_WEIGHTS`, `..._FRONTIER_WEIGHTS`, `..._FRONTIER_ALERT_THRESHOLD`, `..._FRONTIER_WEEKDAY`, `GITHUB_TOKEN`/gh, changelog feed list. Migration additive; first run seeds frontier baseline silently (cold-start gate, reused).

## 9. Testing & CI
- **Pure + offline (TDD):** `action_power` classification (per class + ambiguous), `frontier_score` (bounded, weight-merge, ordering), tier-promotion logic, write-priority ranker (deterministic ordering), digest rendering (golden file), markdown-safety (reuse the capability_report sanitizers).
- **Fixtures:** official-incremental parsing, github_watch delta parsing (mocked API), changelog feeds.
- **Live-contract (scheduled, non-blocking):** official `updated_since` returns data; a sample of write-likely remote servers verify via `tools/list`.
- **No regressions:** the existing daily run + reports unchanged; additive only.

## 10. Risks & Trade-offs
| Risk | Mitigation |
| --- | --- |
| Discovery cost/time scaling `tools/list` | Write-prioritized cap + rotation + per-host throttle (existing netguard); cap is env-tunable; runs on the Eastern-time box. |
| stdio servers stay unverifiable | Explicitly out of scope; digest labels them "emerging/claimed"; documented coverage gap. |
| GitHub API rate limits | gh auth + cached star snapshots + per-run cap; degrade to no-momentum, never crash. |
| Action-power heuristic is fuzzy | Transparent keyword/schema rules, env-tunable weights, confidence flag; calibrate against the Grok radar + spot checks. |
| Weekly latency for non-alerts | Same-day alerts cover the urgent; weekly is for the rounded-up rest. |
| Score gaming / corroboration noise | Corroboration counts *independent* sources only; headlines gate on verified evidence. |

## 11. Success Metrics
- **Verified-write coverage** climbs materially (40 → hundreds) within a few weekly cycles.
- **Time-to-surface** a new major write connector ≤ 1 week (≤ 1 day for standout alerts).
- Every digest item ships with `{action class, evidence tier, example prompt, source, recency}`; headline items are all verified.
- Operator spot-check: the weekly digest's top-10 matches independent "what's new in write-capable MCP" judgment (and the Grok radar).

## 12. Sequencing & Next Step
Dependency-ordered **P1 → P2 → P3 → P4** (verify → score → catch-new → push). Each phase becomes its own `writing-plans` implementation plan, TDD'd and reviewed (matching the pipeline-hardening cadence). Recommended first plan: **P1** (write-prioritized verification + annotation capture) — the trust foundation everything else ranks on.

## 13. Operational Note
The added discovery/ingestion runtime lands on the daily job (Eastern-time machine). The weekly digest is emitted on a configured weekday; standout alerts ride the daily run. Claude-in-Chrome / Grok radar stays operator-run and is fused into the digest when fresh radar data exists.
