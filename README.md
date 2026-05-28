# MCP Write-Capability Report: 2026-05-28

## Write Alerts

| Event | Provider | Server | Tool | Confidence | Summary |
| --- | --- | --- | --- | --- | --- |
| new_write_server | codex | `deepnote` |  | high | New write-capable codex plugin: Deepnote |
| new_write_server | codex | `datadog` |  | high | New write-capable codex plugin: Datadog (Preview) |
| new_write_server | codex | `airtable` |  | high | New write-capable codex plugin: Airtable |

## Coverage

- Normalized servers: 380
- Write-capable servers: 66
- claude: 24 servers, 8 write-capable
- codex: 146 servers, 50 write-capable
- gemini: 201 servers, 8 write-capable
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
