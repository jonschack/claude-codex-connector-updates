# MCP Write-Capability Report: 2026-05-26

## Write Alerts

No high- or medium-confidence write-capability changes were detected today.

## Coverage

- Normalized servers: 384
- Write-capable servers: 62
- claude: 24 servers, 8 write-capable
- codex: 124 servers, 46 write-capable
- gemini: 227 servers, 8 write-capable
- grok: 9 servers, 0 write-capable

## Crawl Issues

- gemini: 2 issue(s)
- grok: 2 issue(s)

- `gemini` `warning` `https://github.com/OutlineDriven/outline-driven-development`: Manifest not found or invalid after probing common paths
- `gemini` `warning` `https://github.com/Paulessus/odin-gemini-mcp-bridge`: Manifest not found or invalid after probing common paths
- `grok` `warning` `https://docs.x.ai/grok/connectors/catalog`: HTTP Error 404: Not Found
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
