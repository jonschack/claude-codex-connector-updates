from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from .classifier import reportable
from .models import CrawlIssue, ServerRecord


def _table(events: List[Dict[str, Any]]) -> str:
    if not events:
        return "No high- or medium-confidence write-capability changes were detected today.\n"
    lines = [
        "| Event | Provider | Server | Tool | Confidence | Summary |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for event in events:
        lines.append(
            "| {event_type} | {provider} | `{server_id}` | {tool} | {confidence} | {summary} |".format(
                event_type=event["event_type"],
                provider=event["provider"],
                server_id=event["server_id"],
                tool=f"`{event['tool_name']}`" if event.get("tool_name") else "",
                confidence=event["confidence"],
                summary=event["summary"].replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def render_daily_report(run_date: str, servers: List[ServerRecord], events: List[Dict[str, Any]], issues: List[CrawlIssue]) -> str:
    provider_counts = Counter(server.provider for server in servers)
    write_servers = [server for server in servers if reportable(server.write_confidence)]
    write_counts = Counter(server.provider for server in write_servers)
    issue_counts = Counter(issue.provider for issue in issues)

    lines = [
        f"# MCP Write-Capability Report: {run_date}",
        "",
        "## Write Alerts",
        "",
        _table(events).rstrip(),
        "",
        "## Coverage",
        "",
        f"- Normalized servers: {len(servers)}",
        f"- Write-capable servers: {len(write_servers)}",
    ]
    for provider in sorted(provider_counts):
        lines.append(f"- {provider}: {provider_counts[provider]} servers, {write_counts[provider]} write-capable")

    lines.extend(
        [
            "",
            "## Crawl Issues",
            "",
        ]
    )
    if not issues:
        lines.append("- None")
    else:
        for provider in sorted(issue_counts):
            lines.append(f"- {provider}: {issue_counts[provider]} issue(s)")
        lines.append("")
        for issue in issues[:25]:
            lines.append(f"- `{issue.provider}` `{issue.severity}` `{issue.source}`: {issue.message}")
        if len(issues) > 25:
            lines.append(f"- ... {len(issues) - 25} additional issue(s) omitted from README; see `data/current/status.json`.")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Local/stdio MCP servers are not executed in v1; they are classified from manifests until Docker/Podman sandboxing is added.",
            "- MCP tool annotations are treated as evidence, not as trusted truth.",
            "- The SQLite state file is the diff source for first-seen and changed write events.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_readme(report: str) -> str:
    suffix = """
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
"""
    return report.rstrip() + "\n\n" + suffix.lstrip()

