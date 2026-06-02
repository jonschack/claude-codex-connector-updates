---
name: grok-research
description: Systematic research sweep for VIRAL MCP / connector capabilities by driving the Grok web UI (grok.com) via Claude-in-Chrome — Grok's live X/Twitter access surfaces what's blowing up that generic web search misses. Harvests Grok's answers, parses them into structured candidates, VERIFIES each against real sources before anything is trusted. Runs an exhaustive query matrix (term variants × a ≥10-like floor × time window) + a seed-account watchlist, and keeps persistent dedup state (data/current/grok_radar_state.jsonl, tracking first_seen + peak_engagement) so repeated sweeps converge on EVERY remotely-viral MCP post — surfacing only what's NEW or RISING — feeding CAPABILITY_HIGHLIGHTS and the meetup description. Operator-run / on-demand (Claude-in-Chrome is interactive — it cannot run in the unattended daily cron). Trigger when the user says /grok-research, "grok sweep", "what MCP went viral", or wants fresh viral capabilities for the meetup.
---

# Grok Research — viral MCP capability sweep (Claude-in-Chrome → grok.com)

Drive the **logged-in Grok web UI** to find what MCP servers/connectors are going viral on X, then turn the answers into **verified** capability candidates for the pipeline. Grok is the source because grok.com is an auth-gated SPA with no public API (verified in recon) and Grok has live X access; Claude-in-Chrome uses the operator's existing session.

> **Posture: candidates → verify first.** X-viral ≠ real, and Grok can hallucinate. Nothing reaches meetup content until it's tagged `verified` (or clearly labeled `claimed`). Never auto-publish anywhere.

## Checklist (create a TodoWrite-style task per step, do in order)
1. Connect a browser
2. Open grok.com (handle login wall)
3. Run the query protocol, harvesting each answer
4. Parse + verify into candidates
5. Write artifacts + report; offer to refresh the meetup description

---

## Step 1 — Connect a browser
Load the Claude-in-Chrome tools (ToolSearch `query: "computer-use"` → no; use `mcp__Claude_in_Chrome__*`). Call `list_connected_browsers`. **If more than one browser is connected, you MUST `AskUserQuestion` listing every browser + the "open a confirmation screen in every Chrome" option** (extension safety gate — one tap, then reuse for the whole run). If exactly one is connected, proceed. Then `tabs_context_mcp(createIfEmpty=true)` to get/!make a tab; reuse that `tabId` for every subsequent call.

## Step 2 — Open Grok
`navigate(tabId, "https://grok.com")`. `get_page_text(tabId)`. If the text shows a sign-in/login wall (no chat input, "Sign in", "Log in to X"), STOP and tell the operator to log into Grok in that Chrome, then re-run. Do not attempt to log in.

## Step 3 — Run the query protocol (the "systematic initiative")
For each query below: locate the prompt input (`find` / `read_page`), type the query (`form_input` or `computer`), submit (Enter), then **wait for the streamed answer to finish** (poll `get_page_text` ~2–3s apart until it stops growing, or wait ~15–25s), and capture the final answer text. Start a fresh chat (new query) for each to avoid context bleed. Append each captured answer to a single raw blob (save to `data/snapshots/<date>/grok/` for audit).

**Always end each query with this format instruction** so parsing is robust. Use a **fenced code block, NOT a markdown table** — `get_page_text` flattens HTML tables and strips the `|` delimiters (confirmed in live testing), but preserves code blocks verbatim:
> "Return ONLY a fenced code block (triple backticks), one row per line, fields separated by ` | `, NOT a markdown table. Columns in order: `name | capability | why_viral | source_url | example_prompt`. One MCP server/connector per row. `source_url` must be a real GitHub repo or official page. `example_prompt` is a natural 'Claude, …' the tool would answer."

> If a prior answer came back as a table (pipes lost on extraction), send one follow-up: *"Re-output the exact same data as a fenced code block, one row per line, fields separated by ' | ', no markdown table."*

**Radar query matrix (the "every post" sweep).** Set Grok to **Heavy** mode (the "Fast" dropdown → **Heavy / Team of Experts** = best X recall). Generate the matrix and have Grok run **each search verbatim** (it executes X advanced-search operators like `min_faves:` and `since:`):

```bash
python3 -c "from mcp_newsletter.grok_research import build_query_matrix; print(chr(10).join(build_query_matrix(min_faves=10, since='YYYY-MM-DD')))"
```

~12 searches: term variants (`"MCP"`/`"model context protocol"`/`"MCP server"`/`"Claude connector"`/…) × `min_faves:10` (the ≥10 "remotely viral" floor) × the window, **plus `from:<seed account>`** sweeps (Anthropic, modelcontextprotocol, ahujasid, …). Feed them to Grok in batches with: *"Run each of these exact X searches and return EVERY matching MCP server/connector as code-block rows — `name | capability | why_viral | source_url | example_prompt` — and put the like/repost count in why_viral."* Forcing the exact searches is what makes recall exhaustive (a free-form prompt let Grok's own broad search return 0 posts in testing). Capture every answer to `data/snapshots/<date>/grok/`.

> **Cadence:** run this on a regular cadence (e.g. 2–3×/week). The dedup state (Step 4) means each run only surfaces what's **new** or **rising** — so over time you converge on "every remotely-viral post," and slow-burners get caught when they cross the floor.

## Step 4 — Parse + verify
Run this (writes the artifacts). It parses every captured answer, verifies each candidate against the awesome-claude-connectors catalog + live URL resolution, and writes results:

```bash
python3 - <<'PY'
import json, datetime
from pathlib import Path
from mcp_newsletter.grok_research import (
    parse_grok_findings, verify_candidates, known_connector_names,
    default_source_checker, to_signal_records)

raw = Path("data/snapshots").glob("*/grok/*answer*.txt")   # the captured answers
text = "\n".join(p.read_text() for p in raw)
findings = parse_grok_findings(text, query="grok-research sweep")

# verification corpus: connector names from the community awesome list (if present)
import subprocess
known = set()
try:
    md = subprocess.run(["gh","api","repos/rdmgator12/awesome-claude-connectors/contents/README.md",
                         "--jq",".content"], capture_output=True, text=True).stdout
    import base64; known = known_connector_names(base64.b64decode(md).decode("utf-8","replace"))
except Exception as e:
    print("known-names fetch skipped:", e)

verify_candidates(findings, source_checker=default_source_checker, known_names=known)

out = Path("data/current"); out.mkdir(parents=True, exist_ok=True)
(out/"grok_research.jsonl").write_text("\n".join(json.dumps(f.to_dict()) for f in findings)+"\n")

# radar dedup state: each sweep only surfaces NEW + RISING (slow-burners crossing the floor)
from mcp_newsletter.grok_research import load_radar_state, merge_into_state, write_radar_state
statep = out/"grok_radar_state.jsonl"
state = load_radar_state(statep)
state, new, rising = merge_into_state(state, [f for f in findings if f.verdict != "rejected"], run_date="YYYY-MM-DD")
write_radar_state(statep, state)
print(f"radar: {len(new)} NEW, {len(rising)} RISING this sweep ({len(state)} total tracked)")

verified = [f for f in findings if f.verdict=="verified"]
claimed  = [f for f in findings if f.verdict=="claimed"]
print(f"harvested={len(findings)} verified={len(verified)} claimed={len(claimed)} rejected={len(findings)-len(verified)-len(claimed)}")
for f in sorted(verified, key=lambda x:x.name):
    print(f"  ✅ {f.name} — {f.capability[:60]} [{f.source_url}]")
PY
```

For higher confidence on a specific candidate, additionally `WebFetch` its `source_url` and confirm the capability is real before featuring it.

## Step 5 — Report + integrate
- Summarize: N harvested, M verified, top viral (verified first).
- The verified/claimed findings are in `data/current/grok_research.jsonl` (provenance `grok:<verdict>`). `to_signal_records()` converts them to SignalRecords if you want to merge into the signals/highlights feed.
- **Offer** to fold the top *verified* viral items into `meetup-hormozi/assets/05-event-page.md` (the event description) — but only `verified`, and keep example prompts honest. Do not edit/publish without the operator's go-ahead.

## Hard rules
- Operator-run only; never claim this runs in the daily cron.
- Never log in to Grok or bypass the browser-selection safety gate.
- `verified` or clearly-labeled `claimed` only in content; drop `rejected`.
- The browser drive has no headless test — validate by a real run; `grok_research.py` parse/verify are unit-tested offline.
