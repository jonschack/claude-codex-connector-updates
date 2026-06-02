from __future__ import annotations

from typing import Dict, List

# Phase 3 content-grade output: the teachable "what you can ask" artifact, built
# from the capability feed (capabilities.json) + notable events (notable.json) +
# news signals (signals.json). Honest tier framing; example prompts illustrative.
# This is a draft for human review — it never auto-publishes anywhere.

_TIER_MARK = {"verified_tools": "✅", "annotation": "•", "claimed_description": "○", "none": "·"}


def _oneline(value: object) -> str:
    """Collapse whitespace/newlines so scraped free text can't break list items."""
    return " ".join(str(value if value is not None else "").split())


def _link(title: object, url: object) -> str:
    safe_title = _oneline(title).replace("]", ")").replace("[", "(")
    safe_url = _oneline(url)
    return f"[{safe_title}]({safe_url})" if safe_url else safe_title


def render_capability_highlights(
    feed: List[Dict[str, object]],
    notable: List[Dict[str, object]],
    signals: List[Dict[str, object]],
    run_date: str,
    top_n: int = 25,
) -> str:
    lines: List[str] = [f"# Capability Highlights — {run_date}", ""]
    lines.append(
        f"What your AI tools can actually do right now — {len(feed)} tool capabilities tracked, "
        f"{len(notable)} notable this run, {len(signals)} recent announcements."
    )
    lines.append("")
    lines.append(
        "> Evidence tiers: ✅ **verified_tools** (observed tool schema) > • **annotation** > "
        "○ **claimed_description** (self-reported, unverified). Example prompts are illustrative."
    )

    lines += ["", "## What you can ask", ""]
    if not feed:
        lines.append("_No tool-level capabilities captured this run._")
    for entry in feed[:top_n]:
        mark = _TIER_MARK.get(str(entry.get("evidence_tier")), "·")
        lines.append(
            f"- {mark} **{_oneline(entry['server'])}** "
            f"(`{_oneline(entry['tool'])}`, {_oneline(entry['provider'])}) — {_oneline(entry['summary'])}"
        )
        lines.append(f"  - Ask: {_oneline(entry['example_prompt'])}  _[{entry['evidence_tier']}]_")
    if len(feed) > top_n:
        lines.append("")
        lines.append(f"_…and {len(feed) - top_n} more in `capabilities.json`._")

    lines += ["", "## Notable new capabilities this run", ""]
    if not notable:
        lines.append("_None._")
    for item in notable[:top_n]:
        if item.get("event_type") == "notable_source":
            lines.append(f"- **{_oneline(item['name'])}**")
        else:
            lines.append(
                f"- **{_oneline(item['name'])}** ({_oneline(item['provider'])}) — "
                f"significance {item.get('score')}, {item.get('tool_count', 0)} tools"
            )

    lines += ["", "## Recent capability announcements", ""]
    if not signals:
        lines.append("_None ingested._")
    for sig in signals[:top_n]:
        lines.append(f"- {_link(sig.get('title', ''), sig.get('url', ''))} — _{_oneline(sig.get('source', ''))}_")

    return "\n".join(lines) + "\n"
