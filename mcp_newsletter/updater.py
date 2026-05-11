from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .classifier import classify_all
from .context import CollectContext
from .providers import collect_all
from .reporting import render_daily_report, render_readme
from .state import all_current, connect, events_for_date, upsert_server, upsert_tool
from .utils import ensure_dir, today_iso, write_json, write_text
from .models import ServerRecord


def _dedupe_servers(servers: List[ServerRecord]) -> List[ServerRecord]:
    by_key = {}
    for server in servers:
        key = (server.provider, server.server_id)
        if key not in by_key:
            by_key[key] = server
            continue
        existing = by_key[key]
        existing.capabilities = sorted(set(existing.capabilities + server.capabilities))
        existing.source_urls = sorted(set(existing.source_urls + server.source_urls))
        existing.tools.extend(server.tools)
        duplicates = existing.metadata.setdefault("duplicates", [])
        duplicates.append(server.to_dict(include_tools=False))
        if not existing.description and server.description:
            existing.description = server.description
    return list(by_key.values())


def run_update(root: Path, run_date: Optional[str] = None, skip_network: bool = False, max_details: int = 200) -> Dict[str, object]:
    run_date = run_date or today_iso()
    ensure_dir(root / "data" / "current")
    ensure_dir(root / "reports")
    ctx = CollectContext(root=root, run_date=run_date, skip_network=skip_network, max_details=max_details)
    servers = _dedupe_servers(collect_all(ctx))
    classify_all(servers)

    db_path = root / "data" / "state.sqlite"
    conn = connect(db_path)
    try:
        for server in servers:
            upsert_server(conn, run_date, server)
            for tool in server.tools:
                upsert_tool(conn, run_date, tool)
        conn.commit()
        events = events_for_date(conn, run_date)
        current_servers = all_current(conn, "servers")
        current_tools = all_current(conn, "tools")
    finally:
        conn.close()

    status = {
        "run_date": run_date,
        "server_count": len(servers),
        "tool_count": sum(len(server.tools) for server in servers),
        "event_count": len(events),
        "issues": [issue.to_dict() for issue in ctx.issues],
    }
    write_json(root / "data" / "current" / "servers.json", current_servers)
    write_json(root / "data" / "current" / "tools.json", current_tools)
    write_json(root / "data" / "current" / "events.json", events)
    write_json(root / "data" / "current" / "status.json", status)
    report = render_daily_report(run_date, servers, events, ctx.issues)
    write_text(root / "reports" / f"{run_date}.md", report)
    write_text(root / "README.md", render_readme(report))
    ctx.finalize_manifest()
    return {"status": status, "events": events, "servers": servers}
