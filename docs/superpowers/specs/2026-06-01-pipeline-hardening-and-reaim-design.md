# Design: Pipeline Hardening & Re-Aim (Capability-Discovery + Trustworthy Monitoring)

- **Date:** 2026-06-01
- **Status:** Implemented P0–P3 on branch `feat/pipeline-hardening` (2026-06-02); each phase reviewed by a subagent reviewer and findings addressed. Live-dependent enrichment (LLM-quality example prompts via an Anthropic key, more signal feeds, per-plugin cursor descriptions) is the documented follow-on.
- **Scope:** Make the research pipeline *fit for its dual objective*. Today it is a
  write-capability auditor; the objective also needs a capability-discovery /
  teaching engine. Repair and harden the ingestion floor first, then build a
  capability/novelty/prompt layer and content-grade output on top.
- **Predecessor:** Extends the two-tier system from
  [2026-05-30 Ecosystem Registry & Vendor Sources](2026-05-30-ecosystem-registry-sources-design.md).
  Grounding audit (file:line evidence) on file; this spec is the response to it.

## 1. Objective, Goals & Non-Goals

### The objective (the thing gaps are measured against)
> Continuously discover and accurately understand the most significant / novel /
> impressive capabilities across the AI-tool ecosystem (Claude connectors, Codex /
> ChatGPT apps, MCP servers, registries) — freshly enough to power **both**
> (a) trustworthy write-capability/safety monitoring **and** (b) content/education
> (the *Cracked Claude Cowork & Codex Club* meetup) that teaches people **what they
> can actually ask their tools to do** (concrete capabilities + example prompts).

### The core diagnosis (why this work exists)
The pipeline answers exactly one question — *which servers can write?* — and the
objective needs three it cannot answer today:
1. **What can this tool actually do?** Tool schemas are discarded after
   classification (`registry_discovery.py:69`); nothing persists tool-level
   capability at scale.
2. **Is that capability new or notable?** The only "new" is *became
   write-capable*. No novelty/significance signal exists (grep: 0 hits).
3. **What's the exact prompt that triggers it?** Nothing stores or generates
   example prompts. No news/changelog ingestion. Output is an auditor's report,
   not a teachable artifact.
Layered on top: coverage is far narrower than it looks (Claude flagship ~27 of
~418; `fetch_text` runs no JS; Codex collector is a dead hardcoded path; 5/10
vendor collectors broken; ~0.2% of servers verified) and it rots silently
(broken source → `[]` + a status line; no alerting; no CI; fixture-only tests).

### In scope
- **Phase 0 — Observability:** make silent rot loud (health floors, alerting,
  live contract tests, CI), fix the hardcoded Codex path.
- **Phase 1 — Ingestion floor:** JS rendering + main-content extraction, full
  Claude directory, repair the 5 broken collectors, public Codex/ChatGPT-apps
  collector, close registry coverage holes.
- **Phase 2 — Capability layer:** persist tool-level capabilities, generate
  evidence-tiered capability summaries + example prompts, a novelty/significance
  signal with its own events, and a news/changelog "signals" tier.
- **Phase 3 — Content output:** a content-grade "Capability Highlights" report +
  machine feed that teaches "what to ask" and feeds the meetup assets.

### Out of scope (explicit)
- **stdio/local server execution** for verification — needs Docker/Podman
  sandboxing; already deferred project-wide. Most registry servers stay
  catalog-classified, not behavior-verified.
- **Full historical backfill / cleanup** of the existing snapshot history —
  separate companion task (already flagged in the predecessor spec).
- **Non-English description NLP** — classifier remains English-keyword; non-EN
  stays `unknown` (pre-existing limitation, documented).
- **Replacing the write-capability monitoring** — objective (a) is preserved
  intact; objective (b) is *added alongside*, sharing the ingestion floor.
- **Auto-publishing meetup copy** — Phase 3 *drafts* content for human review; it
  never posts to Meetup.com or social on its own.

## 2. Design Principles

1. **Extend, don't rewrite.** Reuse `CollectContext`, `ServerRecord`/
   `RegistryServerRecord`, the two-tier model, evidence tiers, `CrawlIssue`,
   snapshot discipline, env-overridable config. New capability lives in new,
   focused modules.
2. **Sequence by dependency, not by excitement.** A teaching engine on
   incomplete/rotting data teaches wrong things *confidently* — the worst failure
   mode. Trust the floor before building the penthouse.
3. **Evidence discipline extends to capability claims.** The four-tier model
   (`verified_tools` > `annotation` > `claimed_description` > `none`) is a
   strength. Capability summaries and **generated example prompts** carry a tier
   too; anything LLM-generated is labeled `generated_unverified` and never
   presented as observed truth.
4. **Fail loud, not silent.** Every "I collected nothing" must be
   distinguishable from "there was nothing to collect," and must page.
5. **Don't break the daily run.** Each phase ships incrementally behind env
   flags; the existing write-capability report keeps working throughout.

## 3. Target Module Layout (additions marked by phase)

```
mcp_newsletter/
  utils.py                 # fetch_text unchanged (non-JS JSON/text sources)
  fetch_rendered.py        # NEW [P1] JS-rendering fetch (Firecrawl backend; Playwright fallback)
  content_extract.py       # NEW [P1] main-content extraction (kills nav boilerplate)
  health.py                # NEW [P0] per-source health floors, escalation, alert payload
  capability.py            # NEW [P2] tool-schema -> capability summary + example prompt (tiered)
  novelty.py               # NEW [P2] significance scoring + notable_capability events
  capability_report.py     # NEW [P3] content-grade "Capability Highlights" + JSONL feed
  signals/                 # NEW [P2] NEWS / CHANGELOG TIER
    __init__.py  base.py   #   SignalSource interface + SignalRecord
    anthropic.py openai.py mcp_blog.py vendor_changelogs.py
  providers/
    claude.py              # CHANGE [P1] rendered full-directory + content extraction
    codex.py               # REWRITE [P1] public ChatGPT-apps/Codex surface (not local FS)
    openai.py cursor.py vscode.py continue_.py   # REPAIR [P1] endpoints/parsers
  registries/              # registry tier (pulsemcp/smithery/gemini cap fixes [P1])
tests/
  live/                    # NEW [P0] live contract/smoke tests (scheduled, not unit)
.github/workflows/
  ci.yml                   # NEW [P0] unit on PR; scheduled live-contract + run-health
```

Each new collector/source is one focused file and degrades to a `CrawlIssue`,
never breaking the run (existing convention, `providers/__init__.py:26`).

## 4. Phase 0 — Observability (make rot loud)

**Goal:** you cannot harden what you cannot see failing. This phase ships first
and is small.

| Workstream | Design |
| --- | --- |
| **Per-source health floor** | `health.py` records a rolling expected-minimum per source (e.g. official > 100, claude > 200 *after* P1). A previously-healthy source returning `0` or `≪ floor` becomes an **`error`-severity** `CrawlIssue`, not a `warning`, and freezes that source's liveness (extends the predecessor's "parser-break floor", §7 there). |
| **Alerting** | The daily email path already exists (`emailer.py`). Add a **health alert**: if any source is `error` or the run's total record count drops `> X%` vs the last good run, send a distinct "PIPELINE DEGRADED" email/notification regardless of whether write-events fired. Today a dead scraper produces a calm, green-looking report. |
| **Live contract tests** | New `tests/live/` suite, **separate from unit tests**: hit each live source, assert min-count + presence of key DOM/JSON markers (e.g. claude page exposes `≥N /connectors/<slug>` links *after rendering*; official registry returns `servers[]`). Catches the staleness fixture tests structurally cannot (a frozen fixture passes even when the live DOM has changed). |
| **CI** | `.github/workflows/ci.yml`: run `unittest` on every PR/push; run the live-contract suite + a `--skip-email` daily smoke on a schedule (e.g. daily) with failures surfaced. The repo currently has **no CI at all**. |
| **Fix hardcoded Codex path** | `codex.py:17` defaults to `/Users/jon/.codex/...`. Make it env-driven with a sane default *and* fold into the P1 rewrite. Removes the perpetual every-run issue. |

**Done when:** a deliberately-broken source turns the run red within one cycle
and pages; CI is green on PRs and visibly red when a live source drifts.

## 5. Phase 1 — Ingestion Floor (coverage + correctness)

**Goal:** complete, trustworthy raw coverage — the data the rest of the system
reasons over. Depends on P0's health floors to prove each fix landed.

### 5.1 JS rendering (`fetch_rendered.py`)
The single highest-impact lever: `fetch_text` is plain `urllib` and runs no
JavaScript (`utils.py:138`), so every client-rendered catalog is silently
under-collected.
- New `fetch_rendered(url, *, wait_for, actions)` parallel to `fetch_text`,
  **opt-in per collector** (JSON-API sources keep using `fetch_text` — no need
  for a browser).
- **Recommended backend: Firecrawl** (`/scrape` for render+markdown,
  `/interact` for scroll/pagination/click). It is already in this environment
  (the `firecrawl-*` skills + MCP), is hosted (no headless-browser dependency on
  the Eastern-time cron box), and returns main-content markdown — solving
  rendering *and* boilerplate in one call. Needs `FIRECRAWL_API_KEY`.
  - **Fallback / self-hosted:** Playwright headless, behind the same interface,
    selected by `MCP_NEWSLETTER_RENDER_BACKEND`.
- Same discipline as `fetch`: snapshot the rendered output, record fetch-meta,
  enforce `MAX_RESPONSE_BYTES`, respect `netguard` SSRF rules.

### 5.2 Main-content extraction (`content_extract.py`)
`html_to_text` flattens the whole page including nav/footer (`utils.py:80`), so
every Claude description is boilerplate. Add a readability-style main-content
step (or use Firecrawl's markdown directly) producing a clean `description`
while the raw snapshot is retained for audit.

### 5.3 Full Claude directory
With rendering + extraction, `claude.py` collects the full directory (handle
pagination/lazy-load via `/interact` scroll). **Target: ≥ 95% of the live
directory** (vs ~6% today). Detail-page descriptions become real capability
text, not nav.

### 5.4 Repair / rewrite the broken collectors
| Provider | Today | Action |
| --- | --- | --- |
| `codex` | hardcoded local FS `/Users/jon/...` → `[]` elsewhere | **Rewrite** to collect the **public** Codex / ChatGPT-apps surface (the group is named for Codex; this is not optional). |
| `openai` | 404 + DOM-changed | Re-derive current connectors endpoint; rendered scrape; live contract test. |
| `cursor` | 429 + DOM-changed | Add throttle/backoff + rendering; or retire explicitly if `cursor.directory/mcp` is gone. |
| `vscode` | 404 + invalid gallery JSON | Point at the current gallery URL/format. |
| `continue` | invalid blocks JSON / SPA | Rendered fetch or corrected API contract. |
A source that is genuinely dead is **retired explicitly** (removed + noted), not
left emitting warnings forever.

### 5.5 Close registry coverage holes
- **pulsemcp:** obtain `MCP_NEWSLETTER_PULSEMCP_KEY` (email `hello@pulsemcp.com`,
  per `OPERATIONS.md`) → ~16k servers currently dark. If still keyless, exclude
  from coverage denominator explicitly (no silent dilution).
- **smithery:** the unauthenticated endpoint caps at ~250–500 unique; document,
  and use `MCP_NEWSLETTER_SMITHERY_KEY` for the full catalog if available.
- **gemini:** the gallery exceeds the 5 MB cap (`netguard.py`) and is dropped
  whole (`utils.py:168`). Stream/paginate instead of dropping; raise the cap for
  that specific source if safe.

**Done when:** Claude coverage ≥ 95%; 0 silently-empty healthy sources; every
collector has a passing live contract test or is explicitly retired;
coverage % in the landscape report reflects real denominators.

## 6. Phase 2 — Capability Layer (the re-aim core)

**Goal:** turn raw coverage into *what each tool can do, how new/notable it is,
and the prompt to trigger it.* Depends on P1 (needs complete, clean data).

### 6.1 Persist tool-level capability
Stop discarding tool schemas (`registry_discovery.py:69`). Extend the record
model with a `tools: [ToolCapability]` list:
`{name, summary, example_prompt, evidence_tier, schema_hash, annotations}`.
- Raise discovery coverage: more workers, and **interest-prioritized** selection
  (notable categories, new servers) on top of the existing deterministic
  rotating cap — not just "has `remote_url`, round-robin".
- stdio/local servers remain unverifiable (out of scope, §1).

### 6.2 Capability summarization + example prompts (`capability.py`)
For servers with usable signal (verified schema preferred; clean description as
fallback), derive:
- a one-line **"can do X"** capability summary, and
- **≥1 example prompt** ("*Claude, …*") — the literal "what to ask" payload.
Implementation: LLM-assisted (Anthropic API; see the `claude-api` skill —
include prompt caching). **Cost control:** only summarize *notable* servers
(§6.3) + cache by `schema_hash`/content hash so unchanged servers never re-spend.
- **Evidence discipline:** prompts derived from an observed schema are
  `verified_tools`-grounded; prompts from description only are
  `claimed_description`; all generated text carries a `generated_unverified`
  flag so nothing is presented as tested. (Mirrors the project's existing
  "annotations are evidence, not trusted truth" stance.)

### 6.3 Novelty / significance signal (`novelty.py`)
A first-class signal **independent of write/read**. A `significance_score` from:
recency (first-seen), capability-class novelty (a tool verb/category not seen
before), category-interest weighting, cross-source corroboration, richness
(write + interactive + multi-tool), and **announcement linkage** (§6.4). Emits
new events alongside the existing write-capability events:
- `notable_capability` — a high-significance new/changed capability.
- `new_tool_capability` — a server gained a materially new tool class.
These are what objective (b) consumes; they do not disturb objective (a)'s
`new_write_server` / `write_status_changed` semantics.

### 6.4 News / changelog "signals" tier (`signals/`)
A third tier (parallel to vendor/registry) ingesting a **small, curated** set of
high-signal feeds — Anthropic news + engineering blog, OpenAI blog, the MCP blog
(`modelcontextprotocol.io`), a few marquee vendor changelogs — via RSS/Atom
where available, else Firecrawl/web-search. Extracts "new capability
announcements" and **links them to catalog entries** (boosting their
significance). This is the narrative layer the meetup needs and the pipeline has
never had. v1 stays deliberately small (a handful of feeds); expansion is later.

## 7. Phase 3 — Content-Grade Output (serves objective b)

**Goal:** a teachable artifact, generated from P2 signals.

- `capability_report.py` produces **"Capability Highlights"**: top-N impressive /
  new capabilities, each as `{tool, capability one-liner, example prompt,
  evidence tier, source URL, recency, category}`, grouped so a mixed room
  (builders + operators + creators) each sees something relevant.
- **Two outputs:** a human/meetup markdown report **and** a `capability_feed.jsonl`
  machine feed.
- **Closes the loop with the meetup workspace:** the feed can auto-draft
  `meetup-hormozi/assets/06-lead-magnet.md` ("What to Ask Your AI" cheat-sheet)
  and a *Connector/Capability of the Week*. Drafts only — a human approves before
  anything is published (§1 out-of-scope).
- The existing write-capability report (`reporting.py`) and `LANDSCAPE_REPORT.md`
  are **untouched**; this is a parallel output.

## 8. Data Model, State & Migration

- **Additive fields** on `ServerRecord`/`RegistryServerRecord`: `tools[]`
  (§6.1), `capability_summary`, `significance_score`, `first_capability_seen`,
  `announcement_refs`.
- **New event types:** `notable_capability`, `new_tool_capability` (registry +
  vendor state).
- **Migration:** new fields are additive and default-empty; the sorted-JSONL
  registry state re-seeds cleanly; the vendor SQLite gains additive columns (or
  rebuilds its local cache — it is rebuildable, not source-of-truth for the
  registry tier). First post-migration run silently seeds capability/novelty
  baselines (reusing the existing cold-start `seeded_at` gate) so it does not
  dump a one-time wall of `notable_capability` alerts.

## 9. Configuration (new env, all overridable)

- `FIRECRAWL_API_KEY`, `MCP_NEWSLETTER_RENDER_BACKEND` (`firecrawl`|`playwright`),
  per-source `..._RENDER=1` opt-in.
- `MCP_NEWSLETTER_HEALTH_FLOOR_<SOURCE>`, `MCP_NEWSLETTER_RUN_DROP_ALERT_PCT`.
- `MCP_NEWSLETTER_SIGNALS` allowlist, per-feed URL overrides.
- `MCP_NEWSLETTER_CAPABILITY_MODEL`, `..._CAPABILITY_BUDGET` (token/cost cap),
  `..._CAPABILITY_ONLY_NOTABLE=1`.
- `MCP_NEWSLETTER_NOVELTY_WEIGHTS` (scoring tunables).
- `MCP_NEWSLETTER_PULSEMCP_KEY`, `..._SMITHERY_KEY` (coverage completeness).

## 10. Testing & CI

- **Keep** all offline fixture parser tests (they guard parsing logic).
- **Add (P0):** `tests/live/` contract suite (min-count + marker assertions per
  source) — the missing freshness guard; runs on a schedule in CI, not in the
  unit run.
- **P1:** rendered-fetch + content-extraction tests against saved rendered
  fixtures (assert nav boilerplate is gone, real description present).
- **P2:** capability summarizer with fixture schemas + **mocked LLM** (no live
  spend in tests), asserting tier labeling + `generated_unverified` flag;
  deterministic `novelty.py` scoring tests; signals parser fixtures.
- **P3:** golden-file test for the capability report; feed-schema validation.
- **CI:** unit on PR; scheduled live-contract + `daily --skip-email` health run.

## 11. Risks & Trade-offs

| Risk | Mitigation |
| --- | --- |
| JS rendering adds an external dependency / cost | Firecrawl is hosted (no browser on the cron box) and already in the toolbelt; opt-in per source so most JSON sources never pay it; Playwright fallback if self-hosting is preferred. |
| LLM summaries/prompts can be wrong ("hype") | Hard evidence tiers + `generated_unverified` flag; prefer verified-schema grounding; cache by hash; **human approves all meetup-facing content**. Aligns with the project's "annotations are evidence, not truth" principle. |
| News ingestion is a mini-project (scope creep) | v1 = a handful of high-signal feeds only; expansion explicitly deferred. |
| Significance scoring is subjective | Weights are env-tunable and the score is transparent (component breakdown logged); start conservative, calibrate against what the meetup actually finds compelling. |
| Daily-run runtime/cost grows | Capability LLM gated to *notable-only* + cached; rendering opt-in; budget caps; the heavy first run is a silent baseline (existing pattern). |

## 12. Success Metrics (per objective)

- **Coverage (a+b):** Claude directory ≥ 95% captured (from ~6%); 0 silently-empty
  healthy sources; all collectors fixed or explicitly retired; registry coverage
  denominators honest.
- **Trust (a):** every *headline* write-capable claim is observed
  (`verified_tools`/`annotation`) or explicitly labeled `claimed`; verification
  rate materially up from ~0.2%.
- **Fitness (b):** every featured capability has `{clean description, ≥1 example
  prompt, evidence tier, source, recency}`; a content-grade report + feed exist;
  `notable_capability` events fire on genuinely new capabilities.
- **Reliability (hardening):** a stale scraper is caught within one run by the
  live-contract suite and pages via the health alert; CI gates PRs.

## 13. Sequencing & Next Step

Phases are dependency-ordered: **P0 → P1 → P2 → P3.** Recommended first
implementation plan bundles **P0 + P1** (observability + ingestion floor) — it is
self-contained, immediately improves objective (a), and is the prerequisite for
everything in P2/P3. Each phase becomes its own `writing-plans` implementation
plan when we execute it; this document is the umbrella design.

## 14. Operational Note
The added runtime (rendering + capped capability LLM calls + signals) lands on
the daily job, which runs on the **Eastern-time machine** (per project memory),
not this Mac. A hosted render backend (Firecrawl) keeps the cron box free of a
headless-browser dependency. This Mac's local environment (no push, Codex path)
is pre-existing and out of scope beyond the P0/P1 Codex fix.
