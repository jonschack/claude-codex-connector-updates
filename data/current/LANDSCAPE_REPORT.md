# MCP Landscape Report

**Snapshot date:** 2026-06-01
**Total records:** 32435

## Change Since Last Run

First run — baseline; no prior snapshot to compare.

## Methodology & Limitations

- **Overall coverage:** 69.8% of known registry totals (succeeded sources only).
- **Sources succeeded:** 6 (official, github_servers, docker, smithery, glama, mcpso)
- **Sources failed:** 1 (pulsemcp) — excluded from coverage numerator.
- **Sampling note:** Representative analysis uses a seeded, deterministic random sampler (I3). Same seed + snapshot → identical sample every run. No 'first N pages' bias.

### Evidence-Tier Definitions

Write-capability claims carry one of four evidence tiers (highest to lowest):

| Tier | Meaning |
|------|---------|
| `verified_tools` | Live tools/list schema observed via MCP discovery |
| `annotation` | MCP readOnlyHint / destructiveHint annotation observed |
| `claimed_description` | Keyword match on self-reported description/tags only — **claimed (unverified)** |
| `none` | No write-capability signal detected |

### Deduplication

- **Unique identities:** 32435
- **Suspected duplicate clusters:** 3762
- **Suspected extra records:** 8037
Adjusted unique estimate: 24398 (after removing suspected duplicates).

## Write-Capable Servers — Broken Out by Evidence Tier

> **Important:** Counts are broken out by evidence tier. Description-only counts are explicitly labeled 'claimed (unverified)'. Headlines cite only `verified_tools` or `annotation` tiers.

| Evidence Tier | Write-Capable Count | Note |
|---------------|---------------------|------|
| `verified_tools` | 40 | Tool schemas directly observed |
| `annotation` | 0 | MCP annotation observed |
| `claimed_description` | 5538 | **claimed (unverified)** — keyword match on self-reported text only |
| **Total write-capable** | **5578** | All tiers combined |
| Not write-capable / none | 26857 | No write signal |

Note: `verified_tools` / `annotation` counts reflect only servers that underwent **live `tools/list` discovery during collection**. A snapshot collected without population-wide discovery will show these as 0 even though many servers are tool-verifiable — run collection with discovery enabled to raise counts from *claimed* to *verified* at scale. The validation section below measures the description heuristic against tool truth on a sample.

## Theme Distribution

### Primary Theme (mutually exclusive)

| Theme | Count |
|-------|-------|
| other | 13268 |
| deploy/cloud/infra | 3855 |
| data/database | 3246 |
| files/docs/storage | 2373 |
| payments/finance/crypto | 2343 |
| browser/computer | 2104 |
| devtools/git | 1887 |
| comms/social | 1469 |
| code-execution | 1289 |
| calendar/booking | 601 |

### Multi-Theme Overlap (servers counted in all matching themes)

| Theme | Count |
|-------|-------|
| other | 13268 |
| files/docs/storage | 4654 |
| data/database | 4595 |
| deploy/cloud/infra | 4106 |
| browser/computer | 3256 |
| devtools/git | 2863 |
| payments/finance/crypto | 2343 |
| comms/social | 2274 |
| code-execution | 1709 |
| calendar/booking | 1353 |

## Top 20 Servers (Ranked)

Ranked by: tier rank DESC, write_confidence DESC, source count DESC, identity ASC. No cherry-picking.

| Rank | Identity | Name | Evidence Tier | Write Confidence | Sources |
|------|----------|------|---------------|------------------|---------|
| 1 | ai.agentrapay/agentra | agentra | `verified_tools` | high | official |
| 2 | ai.autonomad/travel | travel | `verified_tools` | high | official |
| 3 | ai.com.mcp/contabo | Contabo (VPS) MCP Server | `verified_tools` | high | official |
| 4 | ai.com.mcp/linkedin | LinkedIn MCP Server | `verified_tools` | high | official |
| 5 | ai.compeller/compel | Compeller | `verified_tools` | high | official |
| 6 | ai.datamerge/mcp | DataMerge MCP | `verified_tools` | high | official |
| 7 | ai.dreamlit/mcp | Dreamlit | `verified_tools` | high | official |
| 8 | ai.memestack/mcp | MemeStack | `verified_tools` | high | official |
| 9 | ai.modulos/demo-booking | Modulos Demo Booking | `verified_tools` | high | official |
| 10 | ai.myriade/myriade | myriade | `verified_tools` | high | official |
| 11 | ai.openmandate/mcp | OpenMandate | `verified_tools` | high | official |
| 12 | ai.plith/plith | plith | `verified_tools` | high | official |
| 13 | ai.quantifyme/quantifyme | quantifyme | `verified_tools` | high | official |
| 14 | ai.aarna/atars-mcp | aTars MCP | `verified_tools` | medium | official |
| 15 | ai.arclan/registry | Arclan MCP Registry | `verified_tools` | medium | official |
| 16 | ai.artidrop/artidrop | artidrop | `verified_tools` | medium | official |
| 17 | ai.auteng/docs | AutEng MCP - Markdown Publishing & Document Share Links | `verified_tools` | medium | official |
| 18 | ai.bankee/inferventis-mcp | Inferventis MCP Server | `verified_tools` | medium | official |
| 19 | ai.baselight/baselight | baselight | `verified_tools` | medium | official |
| 20 | ai.bezal/local-commerce | Bezal — Local Business Intelligence for AI Agents | `verified_tools` | medium | official |

## Per-Source Coverage Detail

| Source | Pulled | Known Estimate | Coverage % |
|--------|--------|----------------|------------|
| docker [OK] | 278 | 250 | 100.0% |
| github_servers [OK] | 14 | 200 | 7.0% |
| glama [OK] | 24861 | 21000 | 100.0% |
| mcpso [OK] | 32 | 12000 | 0.3% |
| official [OK] | 6285 | 5000 | 100.0% |
| pulsemcp [FAILED] | 0 | 16000 | 0.0% |
| smithery [OK] | 247 | 7000 | 3.5% |

### Coverage Notes

- Source 'pulsemcp' was enabled but did not succeed.
