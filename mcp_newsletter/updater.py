from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from .capability import build_capability_feed, enrich_servers
from .capability_report import render_capability_highlights
from .action_class import coverage_by_action_class
from .classifier import classify_all
from .health import REGISTRY_FLOORS, VENDOR_FLOORS, floors_from_env, summarize_health
from .novelty import notable_events
from .signals import collect_signals
from .context import CollectContext
from .providers import collect_all
from .registries import collect_all_registries, enabled_sources
from .registries.merge import merge_entries, build_alias_map
from .manifest import run_manifest_pass, select_manifest_candidates
from .registry_classify import OBSERVED_EVIDENCE_KINDS, classify_registry_record
from .registry_discovery import select_discovery_candidates, run_discovery
from .registry_state import RegistryMeta, diff_and_events, load_state, write_state
from .registry_reporting import render_registry_section
from .reporting import render_daily_report, render_readme
from .state import all_current, connect, events_for_date, seeded_providers, upsert_server, upsert_tool
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


def _prior_count(root: Path, filename: str, key: str) -> Optional[int]:
    path = root / "data" / "current" / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get(key)
        return int(value) if value is not None else None
    except Exception:
        return None


def _read_prior_servers(root: Path) -> Optional[List[dict]]:
    """Prior servers.json as a list, or None if absent (first run / cold start)."""
    path = root / "data" / "current" / "servers.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except Exception:
        return None


def run_update(root: Path, run_date: Optional[str] = None, skip_network: bool = False, max_details: int = 200) -> Dict[str, object]:
    run_date = run_date or today_iso()
    ensure_dir(root / "data" / "current")
    ensure_dir(root / "reports")
    ctx = CollectContext(root=root, run_date=run_date, skip_network=skip_network, max_details=max_details)
    prior_total = _prior_count(root, "status.json", "server_count")
    prior_servers = _read_prior_servers(root)
    servers = _dedupe_servers(collect_all(ctx))
    classify_all(servers)

    # --- Phase 2 capability layer: enrich tools, build the "what to ask" feed,
    # detect notable new capabilities, and ingest news/changelog signals ---
    enrich_servers(servers)
    # capability_feed is built from THIS run's live collection (not the cumulative
    # servers.json) — we teach only from sources confirmed live this run.
    capability_feed = build_capability_feed(servers)
    notable = []
    if prior_servers is not None:  # cold-start: seed silently on the very first run
        seen_ids = {f"{r.get('provider')}/{r.get('server_id')}" for r in prior_servers}
        notable = notable_events(servers, seen_ids)
    signals = [s.to_dict() for s in collect_signals(ctx)]

    # --- pipeline health (P0): make empty/degraded sources loud, not silent ---
    vendor_counts = dict(Counter(s.provider for s in servers))
    drop_pct = float(os.environ.get("MCP_NEWSLETTER_RUN_DROP_ALERT_PCT", "50"))
    health = summarize_health(
        vendor_counts,
        floors_from_env(VENDOR_FLOORS),
        total_now=len(servers),
        total_prev=prior_total,
        drop_pct=drop_pct,
    )
    for src in health["sources"]:
        if src["status"] != "ok":
            ctx.add_issue(src["source"], "health", src["message"], severity="error")

    db_path = root / "data" / "state.sqlite"
    conn = connect(db_path)
    try:
        seeded = seeded_providers(conn, run_date)
        for server in servers:
            upsert_server(conn, run_date, server, provider_seeded=server.provider in seeded)
            for tool in server.tools:
                upsert_tool(conn, run_date, tool, provider_seeded=server.provider in seeded)
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
        "capability_count": len(capability_feed),
        "notable_count": len(notable),
        "signal_count": len(signals),
        "health": health,
        "issues": [issue.to_dict() for issue in ctx.issues],
    }
    write_json(root / "data" / "current" / "servers.json", current_servers)
    write_json(root / "data" / "current" / "tools.json", current_tools)
    write_json(root / "data" / "current" / "events.json", events)
    write_json(root / "data" / "current" / "status.json", status)
    write_json(root / "data" / "current" / "capabilities.json", capability_feed)
    write_json(root / "data" / "current" / "notable.json", notable)
    write_json(root / "data" / "current" / "signals.json", signals)
    write_text(
        root / "data" / "current" / "CAPABILITY_HIGHLIGHTS.md",
        render_capability_highlights(capability_feed, notable, signals, run_date),
    )
    report = render_daily_report(run_date, servers, events, ctx.issues)
    write_text(root / "reports" / f"{run_date}.md", report)
    registry_result = run_registry_update(root, run_date=run_date, skip_network=skip_network)
    full_report = report.rstrip() + "\n\n" + registry_result["section"]
    write_text(root / "reports" / f"{run_date}.md", full_report)
    report = full_report
    write_text(root / "README.md", render_readme(report))
    ctx.finalize_manifest()
    return {"status": status, "events": events, "servers": servers}


def run_registry_update(root: Path, run_date: Optional[str] = None, skip_network: bool = False) -> Dict[str, object]:
    run_date = run_date or today_iso()
    ensure_dir(root / "data" / "current")
    ctx = CollectContext(root=root, run_date=run_date, skip_network=skip_network)

    state_path = root / "data" / "current" / "registry_state.jsonl"
    meta_path = root / "data" / "current" / "registry_meta.json"
    prior = load_state(state_path)
    meta = RegistryMeta.load(meta_path)
    aliases = build_alias_map(list(prior.values()))

    collection = collect_all_registries(ctx)
    records = merge_entries(collection.entries, aliases)

    # Carry prior OBSERVED state forward onto the freshly-merged records (which
    # start with empty evidence/tools). Discovery/manifest only touch a capped
    # slice each run, so without this the verified/declared evidence and the
    # bounded tools of every un-probed server would be dropped next run — and the
    # P1-0 annotation-merge fix would silently revert. classify_registry_record
    # union-merges these with this run's catalog evidence.
    current = {rec.identity: rec for rec in records}
    for identity, rec in current.items():
        if identity not in prior:
            continue
        prev = prior[identity]
        if not rec.evidence:
            rec.evidence = [e for e in prev.evidence
                            if e.get("kind") in OBSERVED_EVIDENCE_KINDS]
        if not rec.tools:
            rec.tools = list(prev.tools)
        for src in ("tools", "manifest"):  # don't let confidence drop on un-reprobed servers
            info = prev.confidence_by_source.get(src)
            if info:
                rec.confidence_by_source.setdefault(src, info)

    # live discovery (deterministic, capped, rotating)
    if not skip_network:
        cap = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DISCOVERY_CAP", "150"))
        cadence = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DISCOVERY_CADENCE_DAYS", "3"))
        workers = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DISCOVERY_WORKERS", "8"))
        # new_identities (priority bucket 1) is fed by the P4 incremental cursor;
        # until P4 lands it stays empty (default).
        candidates = select_discovery_candidates(list(current.values()), cap, meta.last_discovered, cadence, run_date)
        discovered = run_discovery(candidates, run_date, workers=workers)
        meta.last_discovered.update(discovered)

        # static manifest pass: lift stdio servers (no remote_url) we can't probe
        m_cap = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_MANIFEST_CAP", "100"))
        m_cadence = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_MANIFEST_CADENCE_DAYS", "7"))
        m_candidates = select_manifest_candidates(
            list(current.values()), m_cap, meta.last_manifest_parsed, m_cadence, run_date)
        parsed = run_manifest_pass(ctx, m_candidates, run_date)
        meta.last_manifest_parsed.update(parsed)

    for rec in current.values():
        classify_registry_record(rec, run_date)

    delist_runs = int(os.environ.get("MCP_NEWSLETTER_REGISTRY_DELIST_RUNS", "3"))
    events, new_state, meta = diff_and_events(prior, current, run_date, collection.source_ok, meta, delist_runs)

    # persist (state + meta written together; report derived from them)
    write_state(state_path, list(new_state.values()))
    meta.dump(meta_path)
    write_json(root / "data" / "current" / "registry_events.json", events)
    per_source = Counter(s for rec in new_state.values() for s in {x.get("source") for x in rec.sources})

    # --- registry-tier health (P0): flag a registry source that collected ~0 ---
    reg_health = summarize_health(
        dict(collection.counts),
        floors_from_env(REGISTRY_FLOORS),
        total_now=len(new_state),
        total_prev=len(prior) or None,
        drop_pct=float(os.environ.get("MCP_NEWSLETTER_RUN_DROP_ALERT_PCT", "50")),
    )
    for src in reg_health["sources"]:
        # only escalate sources we actually attempted this run (enabled);
        # a disabled source legitimately reports 0.
        if src["status"] != "ok" and src["source"] in collection.counts:
            ctx.add_issue(src["source"], "health", src["message"], severity="error")

    summary = {
        "run_date": run_date,
        "indexed": len(new_state),
        "write_capable": sum(1 for r in new_state.values() if r.write_confidence in {"medium", "high"}),
        "event_count": len(events),
        "enabled_sources": enabled_sources(),
        "source_ok": collection.source_ok,
        "per_source": dict(per_source),
        "per_source_raw": dict(collection.counts),
        "health": reg_health,
        "coverage_by_action_class": coverage_by_action_class(new_state),
        "issues": [i.to_dict() for i in ctx.issues],
    }
    write_json(root / "data" / "current" / "registry_summary.json", summary)

    manifest_lines = [f"# Registry evidence — {run_date}", ""]
    for e in events:
        manifest_lines.append(f"## {e['event_type']} — {e['identity']} ({e['confidence']})")
        manifest_lines.append(e["summary"])
        for ev in e.get("evidence", []):
            manifest_lines.append(f"- {ev.get('kind')}: {ev.get('value')} [{ev.get('confidence')}]")
        manifest_lines.append("")
    write_text(root / "data" / "current" / "registry_evidence.md", "\n".join(manifest_lines) + "\n")

    new_source_count = sum(1 for e in events if e["event_type"] == "new_source")
    section = render_registry_section(run_date, new_state, events, enabled_sources(), dict(per_source), new_source_count)
    write_text(root / "data" / "current" / "registry_section.md", section)
    # distinct manifest label so this does NOT clobber run_update's _run/manifest.json
    ctx.save_raw_json("_run", "registry-manifest", {
        "run_date": run_date,
        "issues": [i.to_dict() for i in ctx.issues],
        "source_ok": collection.source_ok,
    })
    return {"event_count": len(events), "indexed": len(new_state), "section": section}
