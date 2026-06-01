# Operations

## Daily Command

```bash
python3 -m mcp_newsletter daily
```

The daily command runs collection, classification, reporting, unit tests, and then commits/pushes when git is initialized and `origin` exists.

## GitHub Bootstrap

This machine does not currently have GitHub CLI installed. After installing and authenticating it, run:

```bash
python3 -m mcp_newsletter check
python3 -m mcp_newsletter bootstrap-github
```

The bootstrap command creates a public `mcp-newsletter` GitHub repository from this workspace unless `origin` is already configured.

You can also run:

```bash
scripts/bootstrap_github.sh
```

## Local/stdio MCP Discovery

V1 does not execute arbitrary local or stdio MCP servers. The collector records local server configs and classifies them from manifests. Add Docker or Podman before enabling live local discovery.

## Daily Email + launchd

The `daily` command also emails the rendered report when SMTP credentials are present in the environment.

Required env vars:

- `MCP_NEWSLETTER_EMAIL_TO` — recipient address
- `MCP_NEWSLETTER_SMTP_USER` — Gmail address used to send
- `MCP_NEWSLETTER_SMTP_PASSWORD` — Gmail **app password** (not your account password; create one at https://myaccount.google.com/apppasswords)

If any are missing, `daily` prints `Email skipped: ...` and exits 0; the update still runs.

To install the daily 7:00 AM launchd job:

```bash
# 1. Fill in your Gmail and app password
$EDITOR scripts/com.openclaw.mcp-newsletter.plist

# 2. Copy into LaunchAgents and load
cp scripts/com.openclaw.mcp-newsletter.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.openclaw.mcp-newsletter.plist

# To trigger immediately for testing:
launchctl start com.openclaw.mcp-newsletter

# To remove:
launchctl unload ~/Library/LaunchAgents/com.openclaw.mcp-newsletter.plist
```

Logs land in `tmp/launchd.out.log` and `tmp/launchd.err.log` (already in `.gitignore`).

To send just the email (skip the update):

```bash
python3 -m mcp_newsletter email --date 2026-05-15
```

## Generated Data

- `data/snapshots/YYYY-MM-DD/` preserves raw source evidence.
- `data/current/` contains normalized latest JSON.
- `data/state.sqlite` stores first-seen/last-seen state and diff history.
- `reports/YYYY-MM-DD.md` is the human-readable daily report.

## Network Safety & Tuning

Shared HTTP/discovery hardening (applies to all collectors):

- `MCP_NEWSLETTER_MAX_RESPONSE_BYTES` — max bytes read from any single
  response (default 5242880 = 5 MiB). Oversized responses are rejected as an
  error rather than buffered.
- `MCP_NEWSLETTER_SSRF_ALLOW` — comma-separated hostnames/IPs allowed to
  bypass the private/loopback/link-local block (e.g. a self-hosted test MCP
  server). Empty by default; only set for trusted local endpoints.

## Smithery Registry

The Smithery collector fetches from the **public** endpoint — no API key required:

```
https://registry.smithery.ai/servers?page=N&pageSize=100
```

Response shape: `{"servers":[...], "pagination":{"currentPage":N,"totalPages":M,...}}`. ~5800 servers across ~58 pages.

- `MCP_NEWSLETTER_SMITHERY_URL` — override base URL (default `https://registry.smithery.ai/servers`)
- `MCP_NEWSLETTER_SMITHERY_MAX` — max entries to collect (default 20000)
- `MCP_NEWSLETTER_SMITHERY_KEY` — optional; if set, sent as `Authorization: Bearer <key>` for any extra access. The public endpoint works without it.

### Fields available in the list

Each server has: `id`, `qualifiedName` (stable id), `displayName`, `description`, `verified`, `useCount`, `remote` (boolean), `homepage`. There is **no repo URL** and **no remote endpoint URL** in the list response — only a `remote: true` boolean indicating the server supports remote deployment.

## PulseMCP Registry

The PulseMCP collector fetches from the Generic Registry spec endpoint:

```
https://api.pulsemcp.com/v0.1/servers
```

### Obtaining a key

Email **hello@pulsemcp.com** to request an API key. Once issued, set:

- `MCP_NEWSLETTER_PULSEMCP_KEY` — required; the API key sent as `X-API-Key`
- `MCP_NEWSLETTER_PULSEMCP_TENANT` — optional; sent as `X-Tenant-ID` if set

### Behaviour without a key

If `MCP_NEWSLETTER_PULSEMCP_KEY` is absent or empty, the collector gracefully skips: it returns `[]` and records a single `info`-severity issue (`"MCP_NEWSLETTER_PULSEMCP_KEY not set; skipping collector"`). The daily run is unaffected — no error is raised and no other collectors are blocked.

### Response format

Responses follow the Generic Registry spec: a top-level `"servers"` list of wrapped objects `{"server":{...},"_meta":{...}}` and a `"metadata"` object with a `"nextCursor"` field for pagination. Entries whose `_meta` contains any value with `{"status": "deleted"}` are silently skipped.

Live MCP tool discovery refuses any URL whose host resolves to a loopback,
private, link-local, reserved, multicast, unspecified, or CGNAT
(100.64.0.0/10) address, and refuses non-http(s) schemes. `fetch_text` retries
transient failures (HTTP 429/5xx and transport errors) up to 3 times with
exponential backoff, honoring a numeric `Retry-After` header.

## Population Discovery Cadence

Daily runs keep `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP` modest (default 150)
and rotate through the population via `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS`
(default 3). This probes roughly 150 servers per day without overloading any
single run.

Periodically — e.g. weekly or after a large registry import — run a **deep
run** to populate or refresh the `verified_tools` evidence tier across the
full population:

```bash
MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP=1500 \
MCP_NEWSLETTER_REGISTRY_DISCOVERY_WORKERS=16 \
MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS=0 \
python3 -m mcp_newsletter registry-update
```

- `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP` — max servers to probe per run (default 150; set high for a deep run, e.g. 1500)
- `MCP_NEWSLETTER_REGISTRY_DISCOVERY_WORKERS` — thread-pool size for concurrent probing (default 8; safe to raise to 16–32 on a fast connection)
- `MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS` — minimum days between re-probing the same server (default 3; set to 0 to probe everything regardless of recency)

## Weekly Classifier Validation

Each landscape report optionally measures the description-only classifier's precision and recall against a seeded sample of remotely-verifiable servers. These per-run metrics are persisted in `data/current/landscape_history.jsonl` and surfaced as a trend line in every subsequent report.

To accumulate meaningful trend data and tighten confidence intervals, run a **deep validation** at least once per week:

```bash
python3 -m mcp_newsletter landscape --root . --validate-sample 300 --seed <week-number>
```

Using the ISO week number as the seed (e.g. `--seed 22` for week 22) keeps results reproducible and comparable across machines. Accumulating validation points over multiple weeks:

- Tightens the 95% confidence intervals on precision and recall (wider CIs with small labeled sets).
- Reveals precision/recall **drift** over time — for example, if new server descriptions shift vocabulary and the heuristic degrades.
- Provides evidence for or against re-tuning classifier thresholds.

The trend line appears automatically in `LANDSCAPE_REPORT.md` once at least two runs with validation data exist in the history file.
