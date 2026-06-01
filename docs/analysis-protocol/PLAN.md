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
