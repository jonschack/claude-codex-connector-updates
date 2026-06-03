# meetup-hormozi

Marketing workspace for **Cracked Claude Cowork & Codex Club**, powered by a dedicated
`meetup-marketer` subagent that applies Alex Hormozi's offer/leads frameworks
([alexsmedile/hormozi-skills](https://github.com/alexsmedile/hormozi-skills)) — adapted for a
**free, in-person** event (the "currency" is time + trust, not money).

## What's here
```
meetup-hormozi/
├── BRIEF.md                 # Source of truth: the meetup, the org, avatars, objections, voice.
│                            # Edit this first whenever something changes — all assets key off it.
├── hormozi-skills/          # The cloned Hormozi skill library (18 skills + orchestrator/subagents).
├── agents/meetup-marketer.md# The marketing subagent definition (canonical copy).
└── assets/                  # Generated, ready-to-use marketing:
    ├── 01-offer.md          #   meetup as a Grand Slam Offer (value stack, time-risk reversal)
    ├── 02-angles.md         #   8 ranked positioning angles, per avatar
    ├── 03-objections.md     #   objections → hidden belief → reframe (DM-ready)
    ├── 04-hooks.md          #   24 ranked hooks/headlines, tagged by channel
    ├── 05-event-page.md     #   ⭐ paste-ready Meetup.com event description (+ 3 titles)
    ├── 06-lead-magnet.md    #   "What to Ask Your AI" cheat-sheet spec + draft
    └── 07-social-posts.md   #   7 posts + a 2-week posting sequence
```

## Winning angle (chosen by the subagent)
**Anti-Hype / Straight-Talk** — *"The AI Meetup for Phoenix Business Owners Who Don't Trust AI
Meetups."* It pre-empts AI-fatigue (the #1 RSVP killer), fits both avatars, and credentials
automationinterns.com as practitioners rather than gurus.

## Use the subagent
The subagent is installed at `.claude/agents/meetup-marketer.md`, so you can invoke it:

```
@meetup-marketer write 15 more local-Phoenix hooks for Facebook groups
@meetup-marketer rewrite the event page for the "Skeptical Doer" avatar only
@meetup-marketer produce the full launch kit        # regenerates assets/01..07
```

It always reads `BRIEF.md` first, reads the relevant `hormozi-skills/skills/<skill>/SKILL.md`,
applies the method (not just a summary), and writes results into `assets/`.

> If `@meetup-marketer` isn't recognized yet, restart Claude Code once so it registers the new
> agent (the definition lives in `.claude/agents/meetup-marketer.md`).

## Optionally use the raw Hormozi skills directly
To call skills like `/hormozi-offer`, `/hormozi-hooks`, `/objection-destroyer` yourself:
```bash
cp -r meetup-hormozi/hormozi-skills/skills/ meetup-hormozi/hormozi-skills/agents/ .claude/
# then restart Claude Code
```

## Highest-leverage next action
Fill in `[DATE] [TIME] [VENUE] [ADDRESS] [CAPACITY] [RSVP_LINK]` in `assets/05-event-page.md`,
publish the Meetup.com event, then post Post 1 from `assets/07-social-posts.md`.
