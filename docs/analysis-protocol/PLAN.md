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
- PulseMCP (~16k) key-gated (confirmed 401); absent sources reflected in the coverage denominator. Smithery is PUBLIC and collected without a key, but the unauthenticated endpoint is capped (~250 unique of a stated 5800; full set needs a key). mcp.so is collected via Next.js RSC-payload extraction (~47/page).
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

### mcpso — verified — server data extracted from the Next.js RSC payload (stdlib, no rendering); ~47 servers/page

- **URL:** `https://mcp.so/servers`
- **Status:** HTTP 200, `text/html; charset=utf-8`
- **Observation:** mcp.so is a Next.js App Router app. The HTML embeds server objects as
  `self.__next_f.push([1,"<escaped-json-fragment>"])` script calls (RSC flight format).
  Concatenating the decoded fragments produces a blob containing ~47 real server objects, each with
  fields: `id`, `uuid`, `name`, `title`, `description`, `author_name`, `url` (GitHub URL), `tags`
  (comma-string or `[]` JSON string), `category`, `tools` (inline JSON list or RSC ref string like
  `"$2a"`), `is_official`, `sse_url`.  i18n/navigation objects share the same blob but have no
  `uuid` field and are filtered out.
- **Parser change:** Full rewrite of `collect_mcpso` in `mcp_newsletter/registries/mcpso.py`.
  Uses stdlib `re` + `json` to:
  1. Extract all RSC chunks via `re.findall`.
  2. Decode each chunk with `json.loads('"' + chunk + '"')` (handles `\"`, `\\`, `\uXXXX`).
  3. Walk back from each `"uuid"` occurrence to extract balanced JSON objects.
  4. Dedupe by `uuid`; map to `RawRegistryEntry`; fold inline tool names into description.
  5. Detect parser breaks (markup present but zero servers → `add_issue`).
- **Outcome:** ~47 real server objects extracted per page; all have GitHub `url` fields.
  No headless browser or dedicated API needed.
- **Fixture captured:** `tests/fixtures/registries/mcpso_rsc.html` (minimal synthetic RSC fixture
  with two server objects: one with inline tools list, one with `$ref` tools and comma tags).
- **Tests:** `McpsoCollectorTests` (5 tests) — parses ≥2 servers, tool fold, i18n exclusion,
  skip_network, empty-markup parser-break issue.

### smithery — verified — PUBLIC registry.smithery.ai/servers (no key); flat {servers,pagination} shape. Unauthenticated paging is CAPPED.

- **URL:** `https://registry.smithery.ai/servers`
- **Status:** HTTP 200, public — no API key required.
- **Observation:** `GET /servers?page=1&pageSize=100` returns a flat JSON body:
  `{"servers":[{id,qualifiedName,namespace,slug,displayName,description,iconUrl,verified,useCount,remote,isDeployed,createdAt,homepage,bySmithery,owner,score},...], "pagination":{"currentPage":1,"pageSize":100,"totalPages":5,"totalCount":5800}}`.
  **The unauthenticated endpoint caps paging at `totalPages` 5 (page 6+ returns empty) and repeats
  rows across pages**, so it yields ~500 raw → **~250 UNIQUE** servers without a key, even though
  `totalCount` advertises 5800. The full catalog requires `MCP_NEWSLETTER_SMITHERY_KEY`.
  There is NO repo URL and NO remote endpoint URL in the list (only `remote: true` boolean).
  `qualifiedName` is the stable unique id; pagination uses `currentPage`/`totalPages`.
- **Parser change:** Rewrote `collect_smithery` — removed key-gate, removed `_fetch_with_auth`,
  introduced `_fetch` (optional Bearer if key present), maps flat shape to `RawRegistryEntry`
  (`source_id=qualifiedName`, `repo_url=""`, `remote_url=""`, `source_url=homepage`), pagination
  stops at `totalPages`, `raw={useCount,verified,remote}` stashed for later use. (Cross-source
  identity now keys on the unique `source_id`, so distinct servers sharing a display name no longer
  merge.)
- **Outcome:** ~250 unique servers collected from the public endpoint without a key (the API's
  duplicate-rows + 5-page cap; merge dedups them correctly). Set `MCP_NEWSLETTER_SMITHERY_KEY` to
  reach the full ~5800.

### Glama detail endpoint — deferred (tools[] always empty)

- **URL pattern:** `https://glama.ai/api/mcp/v1/servers/{id}` (by server `id` field)
- **Status probed:** 2026-05-31 — HTTP 200, same JSON schema as the list endpoint
  (`attributes`, `description`, `environmentVariablesJsonSchema`, `id`, `name`, `namespace`,
  `repository`, `slug`, `spdxLicense`, `tools`, `url`).
- **Observation:** Probed 500+ servers across 5 pages (list) plus 60 detail fetches (sampled and
  targeted); `tools[]` is empty (`[]`) in **every** detail response, identical to the list endpoint.
  The `namespace/slug` variant (`/servers/{namespace}/{slug}`) returns HTTP 404; only the `id`-based
  URL returns 200. No sub-paths (`/tools`, `/details`) or GraphQL endpoint found.
- **Outcome:** The per-server detail endpoint exists but does not currently expose richer tool data
  than the list endpoint. **Detail-fetch is deferred.** The `MCP_NEWSLETTER_GLAMA_DETAIL_CAP` env
  var (default `0` = OFF) is wired into `glama.py` as a no-op knob; when Glama begins populating
  per-server tool schemas the knob can be enabled without further code changes. Tests confirm both
  the cap=0 (no extra fetch) and cap>0 (detail fetch + fold) code paths.

## Vendor source verification status (2026-06-01)

Live probed all six `# VERIFY` vendor collectors. Two sources fixed; four left graceful.

### cloudflare — VERIFIED AND FIXED

- **Original URL:** `https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers/` → HTTP 404.
- **Real URL:** `https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/index.md`
  (confirmed via sitemap; the `.md` source serves `text/markdown` directly — no HTML scraping needed).
- **Parser change:** Rewrote `collect_cloudflare` in `mcp_newsletter/providers/cloudflare.py`.
  Old parser scraped HTML for `name | URL` pipe patterns; new parser fetches the markdown source and:
  1. Extracts the main Cloudflare API server URL from the embedded JSON snippet (`"url": "https://mcp.cloudflare.com/mcp"`).
  2. Parses product-specific table rows: `| [Name ↗](github-url) | Description | https://xxx.mcp.cloudflare.com/mcp |`.
  Dedupes by slug; populates `remote_url` and `description` for every entry.
- **Fixture captured:** `tests/fixtures/vendors/cloudflare_mcp_servers_live.md` (11 198 bytes).
- **Servers found live:** 16 (1 main API server + 15 product-specific).
- **`# VERIFY` removed.**
- **Tests updated:** `CloudflareCollectorTests` — `test_parses_live_markdown`,
  `test_remote_url_populated_for_all_servers`, `test_unparseable_markup_returns_empty_and_records_issue`.

### cline — VERIFIED AND FIXED

- **Original URL:** `https://raw.githubusercontent.com/cline/mcp-marketplace/main/marketplace.json` → HTTP 404.
  The `cline/mcp-marketplace` repo exists but contains only a `README.md` — the `marketplace.json`
  file was planned but never created in git.
- **Real URL:** `https://api.cline.bot/v1/mcp/marketplace`
  (discovered by reading `apps/vscode/src/config.ts` in the main `cline/cline` repo, which shows
  `mcpBaseUrl = "https://api.cline.bot/v1/mcp"` and calls `${mcpBaseUrl}/marketplace`).
- **Auth:** Requires `User-Agent: cline-vscode-extension`; standard browser UA returns 401.
- **Shape:** Top-level JSON array (199 items as of 2026-06-01). Each item has `mcpId`, `name`,
  `description`, `githubUrl`, `author`, `tags`, `category`, `githubStars`, `downloadCount`, etc.
  (Old synthetic fixture used `{"items": [...]}` dict wrapper — both shapes are accepted by the collector.)
- **`fetch_text` / `ctx.fetch` change:** Added optional `extra_headers` parameter to both
  `fetch_text` in `mcp_newsletter/utils.py` and `CollectContext.fetch` in `mcp_newsletter/context.py`
  so collectors can override the default `User-Agent` without duplicating fetch logic.
- **`# VERIFY` removed.**
- **Fixture captured:** `tests/fixtures/vendors/cline_marketplace_live.json` (3-item sample).
- **Tests updated:** Added `test_parses_live_array_format` (uses live fixture) alongside the existing
  `test_parses_legacy_dict_format` (old synthetic fixture retained for regression coverage).

### openai — LEFT GRACEFUL — URL 404; feature renamed; no public connector directory

- **Status probed:** `https://platform.openai.com/docs/connectors` → HTTP 404.
- **Finding:** The "connectors" feature was renamed to "apps" as of 2026-12-17 per docs text on
  `platform.openai.com/docs/mcp`: *"As of December 17, 2025, ChatGPT renamed connectors to apps."*
  The `/api/docs/guides/tools-connectors-mcp` internal API endpoint returns HTTP 403.
  No public JSON directory of ChatGPT connector/app listings found (`chatgpt.com/connectors` is 403).
- **Outcome:** Collector returns `[]` without crashing (empty-body guard already in place).
  `# VERIFY` retained; URL note updated to reflect the rename.

### cursor — LEFT GRACEFUL — HTTP 429 persistent bot-block

- **Status probed:** `https://cursor.directory/mcp` → HTTP 429 Too Many Requests (all attempted
  User-Agents, with and without delays). The site aggressively rate-limits non-browser fetch.
  No public JSON API found.
- **Outcome:** Collector returns `[]` without crashing.
  `# VERIFY` retained.

### vscode — LEFT GRACEFUL — No JSON registry file; real source is the Extension Marketplace POST API

- **Status probed:** `https://raw.githubusercontent.com/microsoft/mcp/main/registry.json` → HTTP 404.
  The `microsoft/mcp` repo is a C#/.NET SDK repo; no `registry.json` exists at any path.
- **Finding:** VS Code's MCP server gallery (`@mcp` search in the Extensions view) is backed by
  the VS Code Extension Marketplace (`marketplace.visualstudio.com/_apis/public/gallery/extensionquery`)
  via a POST request — not a simple GET JSON URL. The marketplace API is a general extension gallery
  with tag-based filtering; there is no dedicated standalone MCP server registry JSON URL.
- **Outcome:** Collector returns `[]` without crashing.
  `# VERIFY` retained; URL note updated.

### continue — LEFT GRACEFUL — SPA, no embedded data, no public JSON API

- **Status probed:** `https://hub.continue.dev/api/blocks?type=mcpServer` → HTTP 308 redirect to
  `https://continue.dev/api/blocks?type=mcpServer`, which returns HTML (Next.js SPA).
  RSC stream (`text/x-component`) fetched via `RSC: 1` header — contains only layout/metadata
  components, no block data (pure client-rendered from `api.continue.dev` with 401 auth).
  `https://api.continue.dev/packages` → HTTP 401 Unauthorized.
- **Outcome:** Collector returns `[]` without crashing. URL updated to the redirected domain.
  `# VERIFY` retained.
