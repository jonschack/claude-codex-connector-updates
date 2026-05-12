# MCP Write-Capability Report: 2026-05-12

## Write Alerts

No high- or medium-confidence write-capability changes were detected today.

## Coverage

- Normalized servers: 374
- Write-capable servers: 59
- claude: 24 servers, 9 write-capable
- codex: 121 servers, 43 write-capable
- gemini: 222 servers, 7 write-capable
- grok: 7 servers, 0 write-capable

## Crawl Issues

- gemini: 4 issue(s)
- grok: 1 issue(s)

- `gemini` `warning` `https://github.com/AvaTar-ArTs/my-powers`: Manifest not found or invalid after probing common paths
- `gemini` `warning` `https://github.com/Banny-Gao/expert-bazi-skill`: Manifest not found or invalid after probing common paths
- `gemini` `warning` `https://github.com/Jylhis/skills`: Manifest not found or invalid after probing common paths
- `gemini` `warning` `https://github.com/OutlineDriven/outline-driven-development`: Manifest not found or invalid after probing common paths
- `grok` `warning` `https://x.ai/news/grok-connectors`: HTTP Error 403: Forbidden

## Notes

- Local/stdio MCP servers are not executed in v1; they are classified from manifests until Docker/Podman sandboxing is added.
- MCP tool annotations are treated as evidence, not as trusted truth.
- The SQLite state file is the diff source for first-seen and changed write events.

## Running Locally

```bash
python3 -m mcp_newsletter update
python3 -m unittest
```

After `gh` is installed and authenticated:

```bash
python3 -m mcp_newsletter check
scripts/run_daily.sh
```
