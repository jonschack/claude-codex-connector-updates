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
