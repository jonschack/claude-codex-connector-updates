# MCP Landscape Analysis Protocol — Initial Improvement Plan

**Date:** 2026-05-31
**Goal:** Turn the ad-hoc "mind-blowing capabilities" analysis into a **reproducible protocol that
delivers maximal completeness and accuracy**, where every conclusion is evidence-graded and every
limitation is explicitly quantified rather than hand-waved.

This document is the **baseline** the post-loop reviews check against (for imperfections and
deviations). Each loop implements a subset of the initiatives below as **tested code + docs**, then
is reviewed exhaustively against this plan.

## North-star principles
1. **Measurement, not vibes.** Counts come with coverage %, sampling method, snapshot date, and
   uncertainty. No bare point-estimates in conclusions.
2. **Evidence hierarchy, never blended.** Every write-capability claim carries a tier:
   `verified_tools` (observed tool schema / MCP annotation) > `annotation` > `claimed_description`
   (keyword over self-reported text). Headlines cite the verified tier.
3. **Representative, not convenient.** Samples are random/stratified with a fixed seed — never
   "first N pages" (which is newest-first). Caps are declared and their effect on coverage stated.
4. **Honest incompleteness.** External limits (key-gated registries, rate caps) are quantified as a
   coverage denominator, not omitted.
5. **Reproducible.** A single command + a methodology doc regenerates the report deterministically
   from a snapshot; ad-hoc throwaway scripts are eliminated.

## Initiatives (acceptance criteria in *italics*)
- **I1 — Evidence-tiered classification.** `tier(record) ∈ {verified_tools, annotation, claimed_description, none}`.
  *Pure, tested; tier derivable from a record's `confidence_by_source` + evidence.*
- **I2 — Coverage accounting.** Report sources_attempted/succeeded, per-source pulled vs best-known
  total, caps hit, `isLatest` filtering, and an overall coverage %.
  *Coverage object emitted; deterministic from inputs.*
- **I3 — Representative sampling.** Deterministic random/stratified sampler with a fixed seed (no
  network, no wall-clock). *Same seed → same sample; documented stratification.*
- **I4 — Dedup hardening + true-unique count.** Canonical identity (reverse-DNS name →
  `repo#subpath` (case-normalized) → source:slug); report residual-dup estimate.
  *Tested against monorepo/mixed-case/cross-source cases.*
- **I5 — Tool-schema-grounded classification.** Use live `tools/list` discovery + MCP annotations
  (`readOnlyHint`/`destructiveHint`) + input schemas; for Glama, use the per-server detail `tools[]`.
  *Discovery results raise a record to `verified_tools`; offline-tested with mocked discovery.*
- **I6 — Classifier validation.** Given a labeled sample (truth from tool schemas), compute
  precision / recall / F1 for the description heuristic, with a Wilson confidence interval.
  *Pure, tested on a synthetic labeled set with known metrics.*
- **I7 — Defined theme taxonomy.** Explicit taxonomy with **mutually-exclusive primary theme** +
  reported multi-theme overlap; English-fallback noted. *Taxonomy is data, not inline regex; tested.*
- **I8 — Systematic ranking.** Rank by (verified tool count, destructive-tool count, then
  popularity where available) — deterministic, no cherry-picking. *Stable sort; tested.*
- **I9 — Uncertainty quantification.** Every reported count carries a basis (verified vs claimed),
  a coverage %, and — for sample-derived rates — a CI. *Report object includes these fields.*
- **I10 — Liveness verification.** Optionally ping remote endpoints; flag dead/redirected listings;
  exclude from "live" counts. *Mockable, offline-tested; network optional.*
- **I11 — Reproducible artifact.** One module `mcp_newsletter/landscape.py` (pure analysis) + a
  `landscape` CLI subcommand that consumes a snapshot and emits `LANDSCAPE_REPORT.md` +
  `landscape_metrics.json`, plus this methodology doc. *No throwaway scripts; CLI tested with skip-network.*

## Loop structure
- **Loop 1 — Analysis core (pure, offline):** I1, I2, I4, I7, I8, I9 as `landscape.py` + unit tests.
- **Loop 2 — Grounding & validation:** I5, I6, I10 (discovery-grounded tiers, classifier validation
  harness, liveness), offline-tested with mocks.
- **Loop 3 — Reproducible run & report:** I3, I11 (sampler + CLI), then a live run producing the
  rigorous report; review the **output** for residual methodology gaps; converge.

After each loop: run the full suite, then review exhaustively for (a) imperfections (bugs, untested
paths, blended evidence, hidden non-determinism) and (b) deviations from this plan; fix inline;
record any accepted deviation in an **As-Built Amendments** section here. Loop until a review pass
finds no material imperfection or undocumented deviation **and** all controllable initiatives (I1–I11)
are implemented with remaining external-bound incompleteness explicitly quantified.

## Explicitly out of scope (external-bound; documented, not "fixed")
- PulseMCP (~16k) requires an API key (`hello@pulsemcp.com`); parser is key-ready and graceful-skips.
- Full 21k+ Glama / multi-registry pulls are time-bound; the protocol reports coverage % rather than
  pretending to exhaustiveness.
- These limits are reported as coverage, not silently dropped.

---

## As-Built Amendments & Convergence

**Status: CONVERGED** (final cross-protocol review, all loops complete, 304 tests green).

Three loops were executed, each followed by an exhaustive review against this plan; findings were
fixed inline. All controllable initiatives I1–I11 are implemented as tested code; remaining
incompleteness is external-bound and explicitly quantified in the report.

**Where each initiative lives:**
- I1 `landscape.evidence_tier` · I2 `landscape.coverage` · I3 `landscape.sample_records` (seeded,
  stratified) · I4 `landscape.estimate_residual_dups` · I5 `landscape.ground_record_with_tools` ·
  I6 `landscape.evaluate_classifier` (+ `wilson_interval`) · I7 `landscape.DEFAULT_TAXONOMY` +
  `assign_themes` · I8 `landscape.rank_servers` · I9 `landscape.summarize` + `wilson_interval` ·
  I10 `landscape.check_liveness`/`mark_liveness` · I11 `landscape_report.py` + `landscape` CLI
  subcommand (`python3 -m mcp_newsletter landscape --root <dir> [--validate-sample N --seed S] [--skip-network]`).

**Accepted deviations (documented, not silently changed):**
- **I8 ranking** uses `(tier, write_confidence, source_count, identity)`; "popularity" is not in the
  snapshot, so source-count is the popularity proxy. Wording in I8 referenced popularity as a future
  signal.
- **`annotation` tier** rarely fires for registry records (their record-level evidence is catalog
  text + a `tools` confidence; tool-level annotations surface only through live discovery via
  `ground_record_with_tools`). The function supports it; it is populated when discovery runs.
- **Validation `predicted_write` is catalog/description-only** (not the blended tier), so the
  precision/recall genuinely measure the description heuristic vs tool-grounded truth.
- **Residual-dup name clustering requires a *distinctive* name** (≥5 chars, not generic like
  "mcp-server") so unrelated servers sharing a generic name are not over-clustered; repo-URL
  clustering remains the high-specificity signal.
- **Word-boundary theme matching** (not bare substring) to avoid false positives
  (e.g. "ci"→"precision"); ambiguous 2-char keywords dropped.
- **Liveness probe uses status only** (no body read) so a large-bodied live endpoint isn't misread.
- **No separate `METHODOLOGY.md`** — this PLAN.md is the methodology doc (per I11 wording).

**Quantified external-bound incompleteness (reported, not hidden):**
- Coverage % per source + overall (vs rough `KNOWN_TOTALS`); only sources that succeeded count.
- PulseMCP (~16k) and Smithery key-gated; absent sources reflected in the coverage denominator.
- Validation precision/recall apply ONLY to the remote-URL subset that answered `tools/list`, with
  a small-sample CI caveat; population `verified_tools`/`annotation` are 0 unless collection runs
  population-wide discovery (explained in the report).
- Adjusted-unique estimate reported alongside raw unique (residual-dup correction).

**Headline finding from the live run (official+Glama snapshot, 26.6% coverage):** of 6,910 records,
1,138 are write-capable **by description only (claimed/unverified)**; `verified_tools`=0 at
population scale (discovery not run population-wide); on a validation sample the description
heuristic showed **high precision, low recall** — i.e. it under-detects true (tool-verified)
write-capability on the remotely-verifiable subset. The protocol now states all of this with
coverage, evidence tiers, CIs, and dedup adjustment rather than a single blended number.

---

## Source verification status (2026-05-31)

Probed with `urllib.request` (UA `mcp-newsletter/0.1`, Accept json/html) from a live network
connection. Results recorded below; parsers updated where the live shape differed from the
synthetic fixture.

### github_servers — verified and fixed

- **URL:** `https://raw.githubusercontent.com/modelcontextprotocol/servers/main/README.md`
- **Status:** HTTP 200, `text/plain; charset=utf-8`
- **Observation:** The README no longer contains a large community server table. As of 2026-05-31
  it links primarily to SDK repos (`modelcontextprotocol/typescript-sdk` etc.) plus a handful of
  archived/community server references (`zencoderai/slack-mcp-server`,
  `brave/brave-search-mcp-server`). `extract_github_repos` yields ~14 links total.
- **Parser change:** None required — `extract_github_repos` still correctly extracts all
  `github.com/owner/repo` links present. The reduced yield (~14 vs previously hundreds) is a
  real change in the README's scope; the official registry is now the canonical listing.
- **`# VERIFY` comment:** removed.
- **Live fixture captured:** `tests/fixtures/registries/github_servers_live.md`

### docker — verified and fixed

- **URL:** `https://api.github.com/repos/docker/mcp-registry/contents/servers` (GitHub contents API)
  + per-server `https://raw.githubusercontent.com/docker/mcp-registry/main/servers/{name}/server.yaml`
- **Status:** HTTP 200 (unauthenticated, 329 server directories returned at time of probe)
- **Observation:** The `server.yaml` schema is **completely different** from the synthetic fixture.
  Real shape (as of 2026-05-31):
  ```yaml
  name: <str>
  meta:
    category: <scalar>
    tags: [list]
  about:
    title: <str>
    description: <str>
  source:
    project: <repo-url>   # local servers
  remote:
    url: <endpoint-url>   # remote servers
  ```
  The old parser read flat-scalar keys (`source:`, `description:`, `longLived:`, `category:`) that
  no longer exist; it would have produced empty fields for all 329 servers.
- **Parser change:** Rewrote `_yaml_value` → `_yaml_scalar` / `_yaml_nested` / `_yaml_list`
  helpers that parse the nested YAML shape. `description` ← `about.description`,
  `repo_url` ← `source.project`, `remote_url` ← `remote.url`, `tags` ← `meta.tags[]` prepended
  with `meta.category`.
- **`# VERIFY` comment:** N/A (was not present in docker.py; synthetic fixture was the gap).
- **Live fixtures captured:** `tests/fixtures/registries/docker_live_listing.json`,
  `docker_live_sqlite_server.yaml`, `docker_live_airtable_server.yaml`,
  `docker_live_ais_fleet_server.yaml`

### mcpso — left graceful (JS-rendered, partial HTML yield)

- **URL:** `https://mcp.so/servers`
- **Status:** HTTP 200, `text/html; charset=utf-8`
- **Observation:** mcp.so is a Next.js app (App Router, no `__NEXT_DATA__` SSR block). The
  returned HTML contains no `<a href="https://github.com/...">` anchor tags. GitHub links are
  embedded as string literals inside JS RSC payload chunks (escaped JSON in `self.__next_f.push`
  calls). `extract_github_repos` finds ~45 links by scanning the full body, but these include
  non-server repos (`astral-sh/uv`, `openai/openai-agents-python`, `zed-industries/zed`,
  `github.com/settings/tokens`) mixed in with real MCP servers. The response does not constitute a
  reliable server directory; a headless browser or a dedicated API call would be needed for
  completeness.
- **Parser change:** None. The existing approach (extract_github_repos on raw HTML body) works for
  what it gets; the parser already saves the raw HTML and returns whatever links are found.
- **Outcome:** Left as-is (graceful, returns partial results). A note is warranted in coverage
  accounting: mcpso yields a small, noisy subset of its catalog via SSR HTML.
- **Live fixture captured:** `tests/fixtures/registries/mcpso_live.html` (representative Next.js
  RSC snippet showing the JS-embedded GitHub link pattern)

### smithery — left graceful (API key required)

- **URL:** `https://registry.smithery.ai/servers`
- **Status:** Not probed (key-gated; `MCP_NEWSLETTER_SMITHERY_KEY` not available in this environment)
- **Outcome:** Parser already correctly returns `[]` + an `info`-severity issue when the key is
  absent. No change made. `# VERIFY` comments remain as a reminder that field names have not been
  confirmed against a live response.
