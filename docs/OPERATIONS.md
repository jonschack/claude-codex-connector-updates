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
