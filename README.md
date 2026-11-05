# scbbl

A planner for SuperCoach BBL. It covers SC points history for every Big Bash player since 2011, a doubles and byes grid for BBL|16, international and overseas-league clashes, automatically detected role changes, rain risk and live SC points during matches.

**Live site:** https://donkalot.github.io/scbbl/

This is an unofficial fan site, not affiliated with SuperCoach, News Corp or Cricket Australia.

## What it does

- **Players**: search every BBL|16 squad player, or everyone since 2011, with SuperCoach price, position and ownership; filter by position, sort by price or ownership. Each player page has a season table, a per-match log, venue splits, last-5 form and a sparkline of SC points.
- **Other competitions**: squad players' records in Tests, ODIs, T20Is, the Sheffield Shield, the One-Day Cup and the overseas T20 leagues. Each shows a last-12-months summary and the last 10 games anywhere. T20 leagues get an SC-equivalent average from the same scoring table, so newcomers can be compared with BBL regulars; the Players list can sort by it.
- **Planner**: games per team per round, with doubles and byes highlighted. Click a round to see its matches and their rain risk. Within the 15-day forecast, a blue dot marks each team's and each squad player's games at Med or High rain risk, with a per-round count of your at-risk games; forecasts more than 7 days out are labelled early. Your squad is shown against the rounds, with captain options (projected average × available games). The squad is saved in localStorage only.
- **Availability**: a timeline of Tests and clashing leagues against the rounds, plus the players linked to each event.
- **Matches**: every BBL|16 fixture with a rain-risk rating. Within 15 days of a match it comes from the Open-Meteo hourly forecast at the ground; before that, from how often the same window (±3 days, past 10 years) has had 1 mm or more. A match page shows the hourly forecast, the squads until the toss, then both XIs with live batting, bowling, fielding and SC points. It updates every 30 seconds while the match is on. Pick a captain from your squad for ×2, and see your squad's total for the match and the round so far.
- **Roles**: club moves, batting-order shifts, newly opening, started or stopped bowling, and curated news. Shifts compare each player's last 3 games with their earlier games over the last 3 seasons.

## Alerts

`worker/` is a Cloudflare Worker that runs every minute and posts to [ntfy](https://ntfy.sh/). Subscribe in the free ntfy app to `scbbl-all`, or to one team, such as `scbbl-hea` or `scbbl-six`. For each league match it sends:

- **T-60**: start time, venue, rain risk from the forecast, and squad players who are unavailable that day.
- **XIs named**: both XIs, with captain and keeper marked, the squad players who were left out, and the toss result. It's sent once the cricket.com.au scorecard lists players, which happens at the toss.

A reminder whose window has already passed is skipped, not sent late. What has been sent is recorded per match and topic in KV, so a failed post to one topic is retried the next minute without repeating the others.

Deploy:

```
cd worker
npx wrangler kv namespace create SENT   # paste the id into wrangler.toml
npx wrangler secret put NTFY_TOKEN      # optional ntfy access token
npx wrangler deploy
```

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
| SC prices, positions, ownership, game rules | SuperCoach JSON saved by hand from a signed-in browser (its API blocks bots) | `curated/sc_raw/`, `pipeline/sc_import.py` |
| Rounds | SuperCoach's `real_fixture` once every league match is covered; until then, the only split that fits SC's saved round 1 and Honeyball's published doubles and byes | `curated/sc_raw/fixture-round*.json`, `curated/rounds.json` |
| Clashes, injuries, news | Hand-curated | `curated/availability.json`, `curated/notes.json` |

SC points are computed from the scorecards using `curated/scoring.json`. They're checked against SuperCoach's official BBL|15 league totals (`previous_total` in its player list): all 93 players' game counts agree, 76 totals are exact, and the rest are off by 199 points in 27,775. What's left is which fielder SuperCoach credits for a shared run-out, which follows no rule we can find, so Cricsheet's shared run-outs are split between the fielders. Byes and leg-byes are not dot balls. The live scorecard names one run-out fielder, who gets the full credit, and its dot count includes byes and leg-byes, so a bowler's live points can run a point or two high. `logic.js` ports the scoring code, and a node test checks that it matches the Python on every 2025-26 line and on a replayed cricket.com.au scorecard. The Hundred uses 5-ball sets, so it gets no SC-equivalent; one-day and first-class get traditional stats only.

Cricsheet uses one person id across every competition, so squad players link without name matching. Newcomers with no BBL history are matched by name (exact, then initials) to the only namesake who has played in the last 3 years.

## SuperCoach snapshot

SuperCoach can't be fetched by a script, so each round, signed in at supercoach.com.au, open these and save each response into `curated/sc_raw/`:

| URL (under `https://www.supercoach.com.au/2026/api/bbl/classic/v1/`) | Save as |
| --- | --- |
| `settings?min=false` | `settings.json` |
| `players-cf?embed=notes,odds,player_stats,positions&round=N` | `players-roundN.json` |
| `real_fixture?round=N` | `fixture-roundN.json` (or the whole fixture as `fixture.json`) |

The build uses the newest players file. Every SC player must match a squad player by team and name; if SuperCoach spells a name differently, map it in `curated/sc_names.json` (`{"SC name": "squad name"}`). SuperCoach doesn't score the finals. Once the saved fixture files cover all 40 league matches, SuperCoach's rounds replace the draft ones, with the finals added as one unscored round. Until then, any saved SC round that disagrees with `curated/rounds.json` fails the build. The Players page says which round the prices are for, and warns once that round is over.

## Refresh and guards

`.github/workflows/refresh-data.yml` runs daily from November to February and weekly the rest of the year. Each run:

1. Downloads Cricsheet and the CA fixture. The other-competition zips are cached for the ISO week. Rain history is only fetched for a match whose venue or time has changed.
2. Runs every guard before writing anything. The guards check that:
   - no season, and no other competition, has fewer matches than `data/baseline.json`
   - at least 95% of squad players have a record outside the BBL
   - the player count hasn't dropped by more than 25%
   - the fixture has exactly 40 league games, 10 per team, inside the season window, with no team playing twice in a day
   - every curated name resolves to a squad player
   - every SuperCoach player matches a squad player, and every saved SC fixture match lines up with a CA fixture, with no overlapping rounds
3. Commits `data/` if anything changed. GitHub Pages redeploys automatically.

If a scheduled run fails, a `data-refresh-failure` issue is opened, or commented on if one is already open. Fixture corrections go in `curated/fixture_overrides.json`, never into the generated files.

Run it locally:

```
python -m pipeline.build
```

## Tests

```
python -m pytest -q               # pipeline units + Playwright smoke test
node --test tests/logic.test.js worker/test/notify.test.js   # logic.js, notifier
```

To try the Worker locally, run `npx wrangler dev --test-scheduled --var SITE:<url> --var NTFY:<url>` and trigger a tick with `curl "http://localhost:8787/__scheduled?cron=*+*+*+*+*"`.

The smoke test needs `pip install -r tests/requirements.txt` and `playwright install chromium`.

## Layout

```
index.html, app.js   UI (hash router, no build step)
logic.js             pure functions shared by the UI and node tests
sw.js                network-first service worker (offline fallback)
pipeline/            Python 3.12, standard library only
worker/              ntfy notifier (Cloudflare Worker, cron every minute)
curated/             hand-edited inputs
data/                generated, committed
```

## Support

If this helps your team, you can buy me a coffee at [ko-fi.com/donkware](https://ko-fi.com/donkware).
