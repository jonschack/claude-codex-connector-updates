"""
I11 — Reproducible landscape report module.

Pure except ``load_snapshot`` (file I/O). No network calls in this module —
discovery is fully injected via ``discover_fn``.

KNOWN_TOTALS: rough public estimates for registry sizes.  Override at
runtime by setting the environment variable ``MCP_NEWSLETTER_KNOWN_TOTALS``
to a JSON object, e.g.::

    MCP_NEWSLETTER_KNOWN_TOTALS='{"glama": 25000}' python3 -m mcp_newsletter landscape …

Values not present in the env-var override keep their defaults.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .landscape import (
    coverage,
    evaluate_classifier,
    evidence_tier,
    rank_servers,
    sample_records,
    summarize,
    ground_record_with_tools,
)
from .landscape_ingest import normalize_vendor_record

# ---------------------------------------------------------------------------
# Known totals (rough public estimates; overridable via env var)
# ---------------------------------------------------------------------------

KNOWN_TOTALS: Dict[str, int] = {
    "official": 5000,
    "glama": 21000,
    "pulsemcp": 16000,
    "smithery": 7000,
    "docker": 250,
    "github_servers": 200,
    "mcpso": 12000,
}


def _effective_known_totals() -> Dict[str, int]:
    """Return KNOWN_TOTALS merged with any override from MCP_NEWSLETTER_KNOWN_TOTALS."""
    result = dict(KNOWN_TOTALS)
    env_val = os.environ.get("MCP_NEWSLETTER_KNOWN_TOTALS", "").strip()
    if env_val:
        try:
            overrides = json.loads(env_val)
            if isinstance(overrides, dict):
                result.update({str(k): int(v) for k, v in overrides.items()})
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return result


# ---------------------------------------------------------------------------
# History constants
# ---------------------------------------------------------------------------

HISTORY_FILE = "landscape_history.jsonl"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def append_history(root: "Path | str", metrics: Dict[str, Any]) -> None:
    """Append a compact summary line to the landscape history JSONL file.

    Writes one JSON object per line to ``root/data/current/landscape_history.jsonl``
    capturing the fields needed for week-over-week diffing.  Creates the directory
    if it does not already exist.

    Parameters
    ----------
    root:
        Project root path.
    metrics:
        Full metrics dict as returned by ``build_report``.  Only a subset of
        fields is persisted.
    """
    root = Path(root)
    history_path = root / "data" / "current" / HISTORY_FILE
    history_path.parent.mkdir(parents=True, exist_ok=True)

    wc = metrics.get("write_capable") or {}
    cov = metrics.get("coverage") or {}
    val = metrics.get("validation")
    val_entry = None
    if val:
        val_entry = {
            "precision": val.get("precision"),
            "recall": val.get("recall"),
            "answered": val.get("answered"),
        }

    entry = {
        "snapshot_date": metrics.get("snapshot_date", ""),
        "total_records": metrics.get("total_records", 0),
        "write_capable": {
            "total": wc.get("total", 0),
            "verified_tools": wc.get("verified_tools", 0),
            "annotation": wc.get("annotation", 0),
            "claimed_description": wc.get("claimed_description", 0),
        },
        "coverage_pct": cov.get("overall_coverage_pct"),
        "validation": val_entry,
    }

    with open(history_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def latest_prior(
    root: "Path | str",
    before_date: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent history entry whose ``snapshot_date`` is strictly
    before *before_date*, or ``None`` if no such entry exists or the file is absent.

    ISO date string comparison is used (lexicographic, which is correct for
    ``YYYY-MM-DD`` format).

    Parameters
    ----------
    root:
        Project root path.
    before_date:
        ISO date string.  Only entries with ``snapshot_date < before_date`` are
        considered.

    Returns
    -------
    The full history entry dict for the most recent qualifying entry, or ``None``.
    """
    root = Path(root)
    history_path = root / "data" / "current" / HISTORY_FILE

    if not history_path.exists():
        return None

    best: Optional[Dict[str, Any]] = None
    with open(history_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            date = entry.get("snapshot_date", "")
            if date < before_date:
                if best is None or date > best.get("snapshot_date", ""):
                    best = entry
    return best


def load_snapshot(
    root: "Path | str",
    include_vendor: bool = False,
    run_date: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read the current snapshot from *root*.

    Reads:
    - ``root/data/current/registry_state.jsonl`` — one JSON record per line
    - ``root/data/current/registry_summary.json`` — the registry summary dict

    Optionally folds in the VENDOR tier from ``root/data/current/servers.json``
    (a JSON list), normalizing each entry via ``normalize_vendor_record``.

    Parameters
    ----------
    root:
        Project root path (string or Path).
    include_vendor:
        If True, extend the returned records with vendor entries from
        ``data/current/servers.json``.  If the file does not exist, no error
        is raised.  Default is False (registry-only; existing behaviour).
    run_date:
        ISO date string passed to ``normalize_vendor_record``.  When empty,
        falls back to ``summary["run_date"]`` if present.

    Returns
    -------
    ``(records, summary)``
    """
    root = Path(root)
    state_path = root / "data" / "current" / "registry_state.jsonl"
    summary_path = root / "data" / "current" / "registry_summary.json"

    records: List[Dict[str, Any]] = []
    with open(state_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    with open(summary_path, "r", encoding="utf-8") as fh:
        summary = json.load(fh)

    if include_vendor:
        servers_path = root / "data" / "current" / "servers.json"
        if servers_path.exists():
            effective_date = run_date or summary.get("run_date", "")
            try:
                with open(servers_path, "r", encoding="utf-8") as fh:
                    vendor_list = json.load(fh)
            except (json.JSONDecodeError, ValueError):
                vendor_list = []  # best-effort enrichment: a corrupt vendor dump
                                  # must not crash the landscape analysis
            for v in (vendor_list or []):
                records.append(normalize_vendor_record(v, effective_date))

    return records, summary


# ---------------------------------------------------------------------------
# I11 — run_validation
# ---------------------------------------------------------------------------

def run_validation(
    records: List[Dict[str, Any]],
    sample_n: int,
    seed: Any,
    discover_fn: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
    run_date: str,
) -> Dict[str, Any]:
    """Run classifier validation on a seeded sample.

    Samples records that have a non-empty ``remote_url``, calls
    ``discover_fn`` for each (which must be injected — no real network in
    this function), grounds each record, then evaluates the description-only
    classifier against the tool-grounded truth.

    Parameters
    ----------
    records:
        Full list of server record dicts.
    sample_n:
        Desired sample size (passed to ``sample_records``).
    seed:
        PRNG seed for ``sample_records``.
    discover_fn:
        ``(record: dict) -> list[tool_dict]`` — called for each sampled
        record.  In production this wraps ``discover_remote_tools`` +
        ``classify_tool``.  In tests a fake is injected so no network is
        hit.
    run_date:
        ISO date string passed to ``ground_record_with_tools``.

    Returns
    -------
    ``evaluate_classifier(labeled)`` dict merged with
    ``{"sample_n": int, "answered": int, "unevaluable": int}``.
    """
    # Filter to records with a remote_url
    candidates = [r for r in records if (r.get("remote_url") or "").strip()]

    sampled = sample_records(candidates, sample_n, seed)

    answered = 0
    unevaluable = 0
    labeled: List[Dict[str, Any]] = []

    for rec in sampled:
        # Capture description-only prediction BEFORE grounding:
        # depends ONLY on the catalog/description tier — not on any pre-existing
        # tool or annotation evidence, which would contaminate the metric.
        catalog_conf = ((rec.get("confidence_by_source") or {}).get("catalog") or {}).get("confidence", "unknown")
        predicted_write = catalog_conf in ("medium", "high")

        # Call discover_fn (injected)
        try:
            tools = discover_fn(rec)
        except Exception:
            tools = []

        if not tools:
            unevaluable += 1
            continue

        # Ground a *copy* so the original records list is not mutated
        grounded = copy.deepcopy(rec)
        ground_record_with_tools(grounded, tools, run_date)

        tier_after = evidence_tier(grounded)
        actual_write = tier_after == "verified_tools"

        labeled.append({"predicted_write": predicted_write, "actual_write": actual_write})
        answered += 1

    metrics = evaluate_classifier(labeled)
    metrics["sample_n"] = sample_n
    metrics["answered"] = answered
    metrics["unevaluable"] = unevaluable
    return metrics


# ---------------------------------------------------------------------------
# I11 — build_report
# ---------------------------------------------------------------------------

_TIER_LABEL: Dict[str, str] = {
    "verified_tools": "verified_tools (tool-schema observed)",
    "annotation": "annotation (MCP hint observed)",
    "claimed_description": "claimed_description (claimed, unverified)",
    "none": "none (not write-capable)",
}


def build_report(
    records: List[Dict[str, Any]],
    summary: Dict[str, Any],
    snapshot_date: str,
    validation: Optional[Dict[str, Any]] = None,
    top_n: int = 15,
    prior_metrics: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Build the landscape report.

    Parameters
    ----------
    records:
        List of server record dicts.
    summary:
        registry_summary dict (from ``load_snapshot``).
    snapshot_date:
        ISO date string.
    validation:
        Optional validation metrics dict from ``run_validation``.
    top_n:
        Number of top servers to include in the ranked table.
    prior_metrics:
        Optional prior-run history entry dict (from ``latest_prior``).  When
        provided, a "Change Since Last Run" section is added showing Δ
        verified-write-capable and Δ coverage.  When ``None``, a baseline note
        is included instead.

    Returns
    -------
    ``(markdown: str, metrics: dict)``

    The *metrics* dict includes ``by_tier``, ``coverage``, and ``validation``
    keys so callers can serialise it to JSON without re-computing.

    Every count that is description-only is labeled "claimed (unverified)"
    in the markdown — never blended with verified counts.
    """
    effective_totals = _effective_known_totals()
    coverage_obj = coverage(summary, effective_totals)
    metrics = summarize(records, coverage_obj, snapshot_date, validation)

    lines: List[str] = []

    # ---- Title ----
    lines.append("# MCP Landscape Report")
    lines.append("")
    lines.append(f"**Snapshot date:** {snapshot_date}")
    lines.append(f"**Total records:** {metrics['total_records']}")
    lines.append("")

    # ---- Change Since Last Run ----
    lines.append("## Change Since Last Run")
    lines.append("")
    if prior_metrics is None:
        lines.append("First run — baseline; no prior snapshot to compare.")
    else:
        prior_date = prior_metrics.get("snapshot_date", "unknown")
        # Current side: use the metrics we just computed
        cur_wc = metrics.get("write_capable") or {}
        cur_verified = cur_wc.get("verified_tools", 0)
        cur_cov_pct = (metrics.get("coverage") or {}).get("overall_coverage_pct") or 0.0
        # Prior side: prior_metrics may be a full metrics dict or a history-entry dict
        prior_wc = prior_metrics.get("write_capable") or {}
        prior_verified = prior_wc.get("verified_tools", 0)
        # coverage_pct key used by history entries; fall back to full metrics shape
        prior_cov_pct = prior_metrics.get("coverage_pct")
        if prior_cov_pct is None:
            prior_cov_pct = (prior_metrics.get("coverage") or {}).get("overall_coverage_pct") or 0.0
        delta_verified = cur_verified - prior_verified
        delta_cov = cur_cov_pct - prior_cov_pct
        sign_v = "+" if delta_verified >= 0 else ""
        sign_c = "+" if delta_cov >= 0 else ""
        lines.append(
            f"Change since {prior_date}: "
            f"verified-write-capable {sign_v}{delta_verified}, "
            f"coverage {sign_c}{delta_cov:.1f} pts"
        )
    lines.append("")

    # ---- Methodology & Limitations ----
    lines.append("## Methodology & Limitations")
    lines.append("")

    # Coverage summary
    cov = metrics["coverage"]
    overall_pct = cov.get("overall_coverage_pct")
    if overall_pct is not None:
        lines.append(f"- **Overall coverage:** {overall_pct:.1f}% of known registry totals (succeeded sources only).")
    else:
        lines.append("- **Overall coverage:** unknown (no known-total estimates for succeeded sources).")

    succeeded = cov.get("sources_succeeded") or []
    failed = cov.get("sources_failed") or []
    lines.append(f"- **Sources succeeded:** {len(succeeded)} ({', '.join(succeeded) if succeeded else 'none'})")
    if failed:
        lines.append(f"- **Sources failed:** {len(failed)} ({', '.join(failed)}) — excluded from coverage numerator.")

    lines.append(
        "- **Sampling note:** Representative analysis uses a seeded, deterministic random sampler "
        "(I3). Same seed + snapshot → identical sample every run. No 'first N pages' bias."
    )
    lines.append("")
    lines.append("### Evidence-Tier Definitions")
    lines.append("")
    lines.append("Write-capability claims carry one of four evidence tiers (highest to lowest):")
    lines.append("")
    lines.append("| Tier | Meaning |")
    lines.append("|------|---------|")
    lines.append("| `verified_tools` | Live tools/list schema observed via MCP discovery |")
    lines.append("| `annotation` | MCP readOnlyHint / destructiveHint annotation observed |")
    lines.append("| `claimed_description` | Keyword match on self-reported description/tags only — **claimed (unverified)** |")
    lines.append("| `none` | No write-capability signal detected |")
    lines.append("")

    # Classifier validation
    if validation:
        prec = validation.get("precision", 0.0)
        rec_val = validation.get("recall", 0.0)
        f1 = validation.get("f1", 0.0)
        prec_ci = validation.get("precision_ci", (0.0, 0.0))
        rec_ci = validation.get("recall_ci", (0.0, 0.0))
        n_answered = validation.get("answered", 0)
        n_unevaluable = validation.get("unevaluable", 0)
        sample_n = validation.get("sample_n", 0)
        lines.append("### Classifier Validation")
        lines.append("")
        lines.append(
            f"Description-only classifier evaluated on a seeded sample of "
            f"{sample_n} servers with remote URLs "
            f"({n_answered} answered tools/list, {n_unevaluable} unevaluable / no tools returned):"
        )
        lines.append("")
        lines.append(f"- **Precision:** {prec:.3f} (95% CI: {prec_ci[0]:.3f}–{prec_ci[1]:.3f})")
        lines.append(f"- **Recall:** {rec_val:.3f} (95% CI: {rec_ci[0]:.3f}–{rec_ci[1]:.3f})")
        lines.append(f"- **F1:** {f1:.3f}")
        lines.append("")
        lines.append(
            "> **Scope:** these precision/recall figures are measured ONLY on servers that expose "
            "a remote URL and answered `tools/list`. They do NOT generalize to the "
            "description-only or local (stdio) majority that has no reachable endpoint; "
            "treat them as the heuristic's accuracy on the *remotely-verifiable* subset."
        )
        lines.append("")
        lines.append(
            f"Labeled-set size: {n_answered} servers — the CI widths above reflect this sample size; "
            f"increase `--validate-sample` for tighter bounds."
        )
        lines.append("")

    # Residual dups
    rdups = metrics.get("residual_dups") or {}
    lines.append("### Deduplication")
    lines.append("")
    lines.append(f"- **Unique identities:** {rdups.get('unique_identities', 0)}")
    lines.append(f"- **Suspected duplicate clusters:** {rdups.get('suspected_dup_clusters', 0)}")
    lines.append(f"- **Suspected extra records:** {rdups.get('suspected_extra_records', 0)}")
    _unique_identities = rdups.get("unique_identities", 0)
    _suspected_extra = rdups.get("suspected_extra_records", 0)
    lines.append(
        f"Adjusted unique estimate: {_unique_identities - _suspected_extra} "
        f"(after removing suspected duplicates)."
    )
    lines.append("")

    # ---- Write-capable Counts BY EVIDENCE TIER ----
    lines.append("## Write-Capable Servers — Broken Out by Evidence Tier")
    lines.append("")
    lines.append(
        "> **Important:** Counts are broken out by evidence tier. "
        "Description-only counts are explicitly labeled 'claimed (unverified)'. "
        "Headlines cite only `verified_tools` or `annotation` tiers."
    )
    lines.append("")

    wc = metrics["write_capable"]
    by_tier = metrics["by_tier"]
    lines.append("| Evidence Tier | Write-Capable Count | Note |")
    lines.append("|---------------|---------------------|------|")
    lines.append(f"| `verified_tools` | {wc.get('verified_tools', 0)} | Tool schemas directly observed |")
    lines.append(f"| `annotation` | {wc.get('annotation', 0)} | MCP annotation observed |")
    lines.append(
        f"| `claimed_description` | {wc.get('claimed_description', 0)} | "
        f"**claimed (unverified)** — keyword match on self-reported text only |"
    )
    lines.append(f"| **Total write-capable** | **{wc.get('total', 0)}** | All tiers combined |")
    lines.append(f"| Not write-capable / none | {by_tier.get('none', 0)} | No write signal |")
    lines.append("")
    lines.append(
        "Note: `verified_tools` / `annotation` counts reflect only servers that underwent "
        "**live `tools/list` discovery during collection**. A snapshot collected without "
        "population-wide discovery will show these as 0 even though many servers are "
        "tool-verifiable — run collection with discovery enabled to raise counts from "
        "*claimed* to *verified* at scale. The validation section below measures the "
        "description heuristic against tool truth on a sample."
    )
    lines.append("")

    # ---- Theme Distribution ----
    lines.append("## Theme Distribution")
    lines.append("")
    lines.append("### Primary Theme (mutually exclusive)")
    lines.append("")
    themes_primary = metrics.get("themes_primary") or {}
    sorted_themes = sorted(themes_primary.items(), key=lambda x: -x[1])
    lines.append("| Theme | Count |")
    lines.append("|-------|-------|")
    for theme, count in sorted_themes:
        if count > 0:
            lines.append(f"| {theme} | {count} |")
    lines.append("")

    lines.append("### Multi-Theme Overlap (servers counted in all matching themes)")
    lines.append("")
    themes_overlap = metrics.get("themes_overlap") or {}
    sorted_overlap = sorted(themes_overlap.items(), key=lambda x: -x[1])
    lines.append("| Theme | Count |")
    lines.append("|-------|-------|")
    for theme, count in sorted_overlap:
        if count > 0:
            lines.append(f"| {theme} | {count} |")
    lines.append("")

    # ---- Top N Ranked Servers ----
    lines.append(f"## Top {top_n} Servers (Ranked)")
    lines.append("")
    lines.append(
        "Ranked by: tier rank DESC, write_confidence DESC, source count DESC, identity ASC. "
        "No cherry-picking."
    )
    lines.append("")
    lines.append("| Rank | Identity | Name | Evidence Tier | Write Confidence | Sources |")
    lines.append("|------|----------|------|---------------|------------------|---------|")

    ranked = rank_servers(records)
    for i, rec in enumerate(ranked[:top_n], start=1):
        tier = evidence_tier(rec)
        tier_display = f"`{tier}`"
        if tier == "claimed_description":
            tier_display = f"`{tier}` (claimed, unverified)"
        wconf = rec.get("write_confidence", "unknown")
        sources = ", ".join(s.get("source", "") for s in (rec.get("sources") or []))
        name = rec.get("name") or ""
        identity = rec.get("identity") or ""
        lines.append(f"| {i} | {identity} | {name} | {tier_display} | {wconf} | {sources} |")

    lines.append("")

    # ---- Per-source coverage detail ----
    lines.append("## Per-Source Coverage Detail")
    lines.append("")
    lines.append("| Source | Pulled | Known Estimate | Coverage % |")
    lines.append("|--------|--------|----------------|------------|")
    per_source = cov.get("per_source") or {}
    for src, info in sorted(per_source.items()):
        pulled = info.get("pulled", 0)
        known = info.get("known_estimate")
        cov_pct = info.get("coverage_pct")
        known_str = str(known) if known is not None else "unknown"
        cov_str = f"{cov_pct:.1f}%" if cov_pct is not None else "unknown"
        status = "OK" if src in succeeded else "FAILED"
        lines.append(f"| {src} [{status}] | {pulled} | {known_str} | {cov_str} |")

    lines.append("")
    if cov.get("notes"):
        lines.append("### Coverage Notes")
        lines.append("")
        for note in cov["notes"]:
            lines.append(f"- {note}")
        lines.append("")

    markdown = "\n".join(lines)
    return markdown, metrics


# ---------------------------------------------------------------------------
# generate_landscape — reusable top-level helper
# ---------------------------------------------------------------------------

def generate_landscape(
    root: "Path | str",
    run_date: str,
    include_vendor: bool = True,
    validate_sample: int = 0,
    seed: int = 0,
    top_n: int = 15,
    discover_fn=None,
) -> Dict[str, Any]:
    """Load the snapshot, build the landscape report + metrics, write both files,
    and return the metrics dict.

    Writes to ``root/data/current/``:

    - ``LANDSCAPE_REPORT.md``
    - ``landscape_metrics.json``

    Validation only runs when ``validate_sample > 0`` **and** a ``discover_fn``
    is provided (network); otherwise validation is ``None``.

    Parameters
    ----------
    root:
        Project root path.
    run_date:
        ISO date string for the snapshot.
    include_vendor:
        Whether to fold in the vendor tier from ``servers.json``.
    validate_sample:
        Sample size for classifier validation; 0 disables it.
    seed:
        PRNG seed for sampling.
    top_n:
        Number of top servers in the ranked table.
    discover_fn:
        ``(record: dict) -> list[tool_dict]`` injected for validation.
        When ``None`` or ``validate_sample == 0``, validation is skipped.

    Returns
    -------
    The metrics dict (same as the second element of ``build_report``).
    """
    root = Path(root)
    records, summary = load_snapshot(root, include_vendor=include_vendor, run_date=run_date)

    validation = (
        run_validation(records, validate_sample, seed, discover_fn, run_date)
        if (validate_sample > 0 and discover_fn)
        else None
    )

    # Read prior BEFORE building (so a run never diffs against itself)
    prior = latest_prior(root, run_date)

    markdown, metrics = build_report(
        records,
        summary,
        snapshot_date=run_date,
        validation=validation,
        top_n=top_n,
        prior_metrics=prior,
    )

    output_dir = root / "data" / "current"
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "LANDSCAPE_REPORT.md").write_text(markdown, encoding="utf-8")
    (output_dir / "landscape_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, default=list),
        encoding="utf-8",
    )

    # Append history AFTER writing the report so a run never diffs against itself
    append_history(root, metrics)

    return metrics
