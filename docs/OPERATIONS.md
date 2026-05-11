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

## Generated Data

- `data/snapshots/YYYY-MM-DD/` preserves raw source evidence.
- `data/current/` contains normalized latest JSON.
- `data/state.sqlite` stores first-seen/last-seen state and diff history.
- `reports/YYYY-MM-DD.md` is the human-readable daily report.
