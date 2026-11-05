# scbbl

A planner for SuperCoach BBL. It covers SC points history for every Big Bash player since 2011, a doubles and byes grid for BBL|16, international and overseas-league clashes, automatically detected role changes, rain risk and live SC points during matches.

**Live site:** https://donkalot.github.io/scbbl/

This is an unofficial fan site, not affiliated with SuperCoach, News Corp or Cricket Australia.

## What it does

- **Players**: search every BBL|16 squad player, or everyone since 2011. Each player page has a season table, a per-match log, venue splits, last-5 form and a sparkline of SC points.
- **Other competitions**: squad players' records in Tests, ODIs, T20Is, the Sheffield Shield, the One-Day Cup and the overseas T20 leagues. Each shows a last-12-months summary and the last 10 games anywhere. T20 leagues get an SC-equivalent average from the same scoring table, so newcomers can be compared with BBL regulars; the Players list can sort by it.
- **Planner**: games per team per round, with doubles and byes highlighted. Click a round to see its matches. Your squad is shown against the rounds, with captain options (projected average × available games). The squad is saved in localStorage only.
- **Availability**: a timeline of Tests and clashing leagues against the rounds, plus the players linked to each event.
- **Matches**: every BBL|16 fixture with a rain-risk rating. Within 15 days of a match it comes from the Open-Meteo hourly forecast at the ground; before that, from how often the same window (±3 days, past 10 years) has had 1 mm or more. A match page shows the hourly forecast, the squads until the toss, then both XIs with live batting, bowling, fielding and SC points. It updates every 30 seconds while the match is on. Pick a captain from your squad for ×2, and see your squad's total for the match and the round so far.
- **Roles**: club moves, batting-order shifts, newly opening, started or stopped bowling, and curated news. Shifts compare each player's last 3 games with their earlier games over the last 3 seasons.

## Data

| What | Source | Where |
| --- | --- | --- |
| Ball-by-ball history, 2011/12 onwards | [Cricsheet](https://cricsheet.org/) `bbl_json.zip` (ODC-BY) | `pipeline/cricsheet.py` |
| BBL\|16 fixture, venues, player display names | cricket.com.au `apiv2` (competition 4691) | `pipeline/fixture.py`, `pipeline/register.py` |
| Other competitions | Cricsheet `<code>_male_json.zip`, 16 competitions (ODC-BY) | `pipeline/elsewhere.py`, `curated/competitions.json` |
| BBL\|16 squads | Wikipedia, entered by hand | `curated/squads.json` |
| SC scoring table | SuperCoach BBL rules | `curated/scoring.json` |
| Live scorecards | cricket.com.au `apiv2` `views/scorecard`, fetched by the browser | `logic.js` `caLines` |
| Rain forecast, rain history | [Open-Meteo](https://open-meteo.com/) forecast (browser) and archive (CC BY 4.0) | `app.js`, `pipeline/climate.py` |
| Rounds | Drafted Mon–Sun weeks until SuperCoach publishes its own | `curated/rounds.json` |
| Clashes, injuries, news | Hand-curated | `curated/availability.json`, `curated/notes.json` |

SC points are computed from the scorecards using `curated/scoring.json`, so official scores can differ. Shared run-outs in Cricsheet are split between the fielders. The live scorecard names one run-out fielder, who gets the full credit. `logic.js` ports the scoring code, and a node test checks that it matches the Python on every 2025-26 line and on a replayed cricket.com.au scorecard. The Hundred uses 5-ball sets, so it gets no SC-equivalent; one-day and first-class get traditional stats only.

Cricsheet uses one person id across every competition, so squad players link without name matching. Newcomers with no BBL history are matched by name (exact, then initials) to the only namesake who has played in the last 3 years.

## Refresh and guards

`.github/workflows/refresh-data.yml` runs daily from November to February and weekly the rest of the year. Each run:

1. Downloads Cricsheet and the CA fixture. The other-competition zips are cached for the ISO week. Rain history is only fetched for a match whose venue or time has changed.
2. Runs every guard before writing anything. The guards check that:
   - no season, and no other competition, has fewer matches than `data/baseline.json`
   - at least 95% of squad players have a record outside the BBL
   - the player count hasn't dropped by more than 25%
   - the fixture has exactly 40 league games, 10 per team, inside the season window, with no team playing twice in a day
   - every curated name resolves to a squad player
3. Commits `data/` if anything changed. GitHub Pages redeploys automatically.

If a scheduled run fails, a `data-refresh-failure` issue is opened, or commented on if one is already open. Fixture corrections go in `curated/fixture_overrides.json`, never into the generated files.

Run it locally:

```
python -m pipeline.build
```

## Tests

```
python -m pytest -q               # pipeline units + Playwright smoke test
node --test tests/logic.test.js   # logic.js
```

The smoke test needs `pip install -r tests/requirements.txt` and `playwright install chromium`.

## Layout

```
index.html, app.js   UI (hash router, no build step)
logic.js             pure functions shared by the UI and node tests
sw.js                network-first service worker (offline fallback)
pipeline/            Python 3.12, standard library only
curated/             hand-edited inputs
data/                generated, committed
```

## Support

If this helps your team, you can buy me a coffee at [ko-fi.com/donkware](https://ko-fi.com/donkware).
