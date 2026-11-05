# scbbl

A planner for SuperCoach BBL. It covers SC points history for every Big Bash player since 2011, a doubles and byes grid for BBL|16, international and overseas-league clashes, and automatically detected role changes.

**Live site:** https://donkalot.github.io/scbbl/

This is an unofficial fan site, not affiliated with SuperCoach, News Corp or Cricket Australia.

## What it does

- **Players**: search every BBL|16 squad player, or everyone since 2011. Each player page has a season table, a per-match log, venue splits, last-5 form and a sparkline of SC points.
- **Planner**: games per team per round, with doubles and byes highlighted. Click a round to see its matches. Your squad is shown against the rounds, with captain options (projected average × available games). The squad is saved in localStorage only.
- **Availability**: a timeline of Tests and clashing leagues against the rounds, plus the players linked to each event.
- **Roles**: club moves, batting-order shifts, newly opening, started or stopped bowling, and curated news. Shifts compare each player's last 3 games with their earlier games over the last 3 seasons.

## Data

| What | Source | Where |
| --- | --- | --- |
| Ball-by-ball history, 2011/12 onwards | [Cricsheet](https://cricsheet.org/) `bbl_json.zip` (ODC-BY) | `pipeline/cricsheet.py` |
| BBL\|16 fixture, venues, player display names | cricket.com.au `apiv2` (competition 4691) | `pipeline/fixture.py`, `pipeline/register.py` |
| BBL\|16 squads | Wikipedia, entered by hand | `curated/squads.json` |
| SC scoring table | SuperCoach BBL rules | `curated/scoring.json` |
| Rounds | Drafted Mon–Sun weeks until SuperCoach publishes its own | `curated/rounds.json` |
| Clashes, injuries, news | Hand-curated | `curated/availability.json`, `curated/notes.json` |

SC points are computed from the scorecards using `curated/scoring.json`, so official scores can differ. Shared run-outs in Cricsheet are split between the fielders.

## Refresh and guards

`.github/workflows/refresh-data.yml` runs daily from November to February and weekly the rest of the year. Each run:

1. Downloads Cricsheet and the CA fixture.
2. Runs every guard before writing anything. The guards check that:
   - no season has fewer matches than `data/baseline.json`
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
python -m pytest -q          # pipeline units + Playwright smoke test
node --test tests/           # logic.js
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
