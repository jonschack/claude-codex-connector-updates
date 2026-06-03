# mcp_newsletter/registry_reporting.py
from __future__ import annotations

from typing import Any, Dict, List

from .action_class import coverage_by_action_class
from .classifier import reportable
from .registries.base import RegistryServerRecord

DOUBLE_COUNT_NOTE = (
    "- Note: a server may also appear in the vendor-tier coverage above; the "
    "two tiers are counted independently."
)


def render_registry_section(
    run_date: str,
    records: Dict[str, RegistryServerRecord],
    events: List[Dict[str, Any]],
    enabled: List[str],
    per_source: Dict[str, int],
    new_source_count: int,
    row_cap: int = 25,
) -> str:
    write_capable = [r for r in records.values() if reportable(r.write_confidence)]
    new_today = [e for e in events if e["event_type"] in {"new_write_server", "write_status_changed"}]

    lines = [
        "## Ecosystem Registries",
        "",
        f"- Indexed servers (deduped): {len(records)} across {len(enabled)} registries",
        f"- Write-capable (medium+): {len(write_capable)}",
        f"- New/changed write-capable today: {len(new_today)}",
    ]
    if per_source:
        per = " · ".join(f"{s} {per_source.get(s, 0)}" for s in sorted(per_source))
        lines.append(f"- Per registry (sums exceed deduped total): {per}")
    if new_source_count:
        lines.append(f"- Existing write-capable servers newly seen in another registry: {new_source_count}")
    lines.append(DOUBLE_COUNT_NOTE)
    lines.append("")

    cov = coverage_by_action_class(records)
    if cov:
        lines += [
            "### Write coverage by action class",
            "",
            "| Action class | Verified | Annotation | Declared | Claimed | Total |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for cls in sorted(cov, key=lambda c: (-cov[c].get("total", 0), c)):
            b = cov[cls]
            lines.append("| {c} | {v} | {a} | {d} | {cl} | {t} |".format(
                c=cls, v=b.get("verified_tools", 0), a=b.get("annotation", 0),
                d=b.get("declared_manifest", 0), cl=b.get("claimed_description", 0),
                t=b.get("total", 0)))
        lines.append("")

    table_events = [e for e in events if e["event_type"] != "new_source"]
    if table_events:
        lines += [
            "### New / changed / delisted write-capable servers",
            "",
            "| Event | Server | Confidence | Seen in | Summary |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in table_events[:row_cap]:
            lines.append(
                "| {et} | `{id}` | {conf} | {src} | {sm} |".format(
                    et=e.get("event_type", ""), id=e.get("identity", ""),
                    conf=e.get("confidence", ""),
                    src=", ".join(e.get("sources", [])),
                    sm=str(e.get("summary", "")).replace("|", "\\|"),
                )
            )
        if len(table_events) > row_cap:
            lines.append(f"- ... {len(table_events) - row_cap} additional event(s); see `data/current/registry_events.json`.")
    return "\n".join(lines) + "\n"
