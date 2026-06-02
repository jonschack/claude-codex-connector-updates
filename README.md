# MCP Write-Capability Report: 2026-06-02

## Write Alerts

| Event | Provider | Server | Tool | Confidence | Summary |
| --- | --- | --- | --- | --- | --- |
| new_write_server | codex | `nvidia` |  | high | New write-capable codex plugin: NVIDIA |
| new_write_server | codex | `posthog` |  | high | New write-capable codex plugin: PostHog |
| new_write_server | codex | `metabase` |  | high | New write-capable codex plugin: Metabase |
| new_write_server | codex | `wix` |  | high | New write-capable codex plugin: Wix |
| new_write_server | codex | `base44` |  | high | New write-capable codex plugin: Base44 |
| tool_schema_changed | gemini | `bigtable-bigtable` | `delete_instance` | high | Write-capable tool changed: gemini/bigtable-bigtable/delete_instance |
| tool_schema_changed | gemini | `bigtable-bigtable` | `create_table` | high | Write-capable tool changed: gemini/bigtable-bigtable/create_table |
| tool_schema_changed | gemini | `bigtable-bigtable` | `delete_table` | high | Write-capable tool changed: gemini/bigtable-bigtable/delete_table |
| tool_schema_changed | gemini | `bigtable-bigtable` | `delete_logical_view` | high | Write-capable tool changed: gemini/bigtable-bigtable/delete_logical_view |

## Coverage

- Normalized servers: 425
- Write-capable servers: 74
- claude: 24 servers, 8 write-capable
- codex: 168 servers, 58 write-capable
- gemini: 224 servers, 8 write-capable
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
