You are running unattended as a daily news check for the SuperCoach BBL|16 planner. The repo is in the current directory (c:\play\scbbl); the site is live at https://bbl.fantasyplanner.au/. BBL|16 runs 12 Dec 2026 to 26 Jan 2027. Nobody is watching this run, so don't ask questions. Decide, and record what you decided.

## Task
Search the web for BBL|16 news since the last check that changes the hand-curated data, and update it.
1. Read `news/open-items.md` and work through each item.
2. Look for anything new:
   - injuries, withdrawals, replacement signings
   - national squads announced
   - overseas players' availability windows
   - captaincy
   - batting-order or role news from club, CA, ESPNcricinfo or Wikipedia pages
   - pitch news at a BBL|16 ground: a re-laid square or new drop-in pitches, a new curator, a pitch rated poor by the ICC/CA, or a curator or pitch report saying how the surface will play this season, including whether it will suit spin or pace
3. Read the curated files before editing them, and skip anything already recorded.

## Files
- `curated/availability.json`
  - `events`: `{id, name, kind (test|intl|league|injury|personal), start, end (YYYY-MM-DD, AEDT), verified, source}`.
  - `links`: `{team, player, event, likely?, from?, until?}`. `from` and `until` (YYYY-MM-DD, inside the event's dates) narrow the event for that one player.
  - A player's event uses kind `personal` or `injury`. Multi-player events are `test`, `intl` or `league`.
  - Australia's Test squad misses the BBL for the whole home series, not just Test days, until Cricket Australia releases them. Link squad players to the series event (`aus-nz-tests`). If a player is released to play BBL, set `until` on his link to the last day he's unavailable; if the report gives no date, use the day the release was announced. If a player joins the squad mid-series (a call-up or injury cover), set `from` to the day he joined. If a released player is recalled, add a second link with `from`. If a player is dropped or released before the series starts, delete his link instead.
- `curated/notes.json`: `{date, team, player, text, source}`, newest relevant first. Write `text` as one or two plain sentences of fact.
- `curated/squads.json`: `teams.<TEAM>` player lists and `captains`. Team codes: HEA HUR REN SCO SIX STA STR THU.
- `curated/venues.json`: keyed by cricket.com.au venue id. Pitch news goes in that ground's `notes` as `{date, text, source}`, written like notes.json. Leave `cricsheet` (the ground's names in Cricsheet) alone unless the build fails asking for a new name; then add the exact name it prints.
- Player names must match `curated/squads.json` exactly.

## Rules
- Every event and note needs a source URL from a page you actually fetched. Prefer the club, cricket.com.au, ESPNcricinfo or the official board; use Wikipedia only when nothing better exists. Use `verified: false` when the date isn't confirmed by an official source.
- Ignore rumours, social-media posts and fantasy tip articles, apart from facts they cite from an official source.
- Never fetch or scrape supercoach.com.au.
- Don't touch code files (`*.js`, `*.py`, `*.html`, `*.ps1`), `curated/sc_raw/`, `data/` by hand, `.github/`, or anything in `news/` other than `news/open-items.md`. `data/` is only ever written by the build.
- Your tools are limited to match. Edit and Write work only under `curated/` and on `news/open-items.md`. The shell runs only the exact commands named in this prompt, plus `git status` and `git diff`. Anything else is denied, so don't look for another way round.
- Update `news/open-items.md`: remove resolved items, and add new open questions you found but couldn't settle.

## Finish
If you changed nothing in `curated/`, end with the line `RESULT: nothing new`, then stop. Leave any `news/open-items.md` edits uncommitted; the wrapper commits them.

Otherwise, run these in order:
1. `python -m pipeline.build`
2. `python -m pytest -q`
3. `node --test tests/ worker/test/`

If any of them fails:
- If your edit caused it, fix your edit and rerun.
- If you can't make all three pass, revert your data changes with `git checkout -- curated data` (keep your `news/open-items.md` notes) and end with `RESULT: failed <one-line reason>`.

When all three pass:
1. Run `git add curated data news/open-items.md`.
2. Run `git commit -m "<message>"` with a one-line message saying what changed, for example "News: Australia's NZ Test squad named; Webster out of BBL rounds 1-2". No Co-Authored-By trailer. Don't push; the wrapper does that.
3. End with `RESULT: committed <the commit message>`.
