# scbbl

A planner for SuperCoach BBL. It covers SC points history for every Big Bash player since 2011, a doubles and byes grid for BBL|16, international and overseas-league clashes, automatically detected role changes, rain risk and live SC points during matches.

**Live site:** https://donkalot.github.io/scbbl/

This is an unofficial fan site, not affiliated with SuperCoach, News Corp or Cricket Australia.

## What it does

- **Players**: search every BBL|16 squad player, or everyone since 2011, with SuperCoach price, position and ownership; filter by position, sort by price or ownership. Each player page has a season table, a per-match log, venue splits, last-5 form and a sparkline of SC points.
- **Other competitions**: squad players' records in Tests, ODIs, T20Is, the Sheffield Shield, the One-Day Cup and the overseas T20 leagues. Each shows a last-12-months summary and the last 10 games anywhere. T20 leagues get an SC-equivalent average from the same scoring table, so newcomers can be compared with BBL regulars; the Players list can sort by it.
- **Planner**: games per team per round, with doubles and byes highlighted. Click a round to see its matches and their rain risk. Within the 15-day forecast, a blue dot marks each team's and each squad player's games at Med or High rain risk, with a per-round count of your at-risk games; forecasts more than 7 days out are labelled early. Your squad is shown against the rounds, with captain options (projected average × available games). The squad is saved in localStorage only.
- **Team**: checks your squad against SuperCoach's $2M cap and its position seats (2 WKP, 7 BAT, 7 BWL, 1 FLX). Dual-position players are seated wherever leaves room for the rest. An open seat lists the best affordable players who fit, keeping the cheapest price in hand for every other open seat. Trade on any player lists replacements within its price plus the money left, with the projected gain and games left.
  - **On field**: for any round, picks the 12 (1 WKP, 5 BAT, 5 BWL, 1 FLX) with the highest expected score (projected average × available games), the three emergencies (one per position, from bench players with a game) and the captain and vice. Keep anyone on or off by hand; the projection counts the best 11 plus the captain again.
  - **Import from SuperCoach**: a bookmarklet, clicked on your own logged-in SuperCoach team page, re-reads the team with your login and opens this site with your squad, on-field 12 and captain. Only SuperCoach player numbers come across; the login token stays on supercoach.com.au. Pasting the `statsPlayers` response from DevTools does the same.
  - **Trades**: after the first lockout, each Swap counts against the round still being played: 3 a round, 26 a season. Undo gives a trade back until that round ends. A boost is assumed to add one trade to a round and still count towards the 26.
- **Availability**: a timeline of Tests, international white-ball series and clashing leagues against the rounds, each with its source, plus the players who miss games. A "likely" link means the squad isn't named yet; the planner still counts those games as missed.
- **Matches**: every BBL|16 fixture with a rain-risk rating. Within 15 days of a match it comes from the Open-Meteo hourly forecast at the ground; before that, from how often the same window (±3 days, past 10 years) has had 1 mm or more. A match page shows the hourly forecast, the squads until the toss, then both XIs with live batting, bowling, fielding and SC points. It updates every 30 seconds while the match is on. Pick a captain from your squad for ×2, and see your squad's total for the match and the round so far.
- **Pitch**: each match page says how the ground has played: the average first innings over the last 5 seasons against the league in the same seasons, season by season, and so far this season. Only full first innings count (20 overs or all out). A ground is called batting- or bowling-friendly only if it's at least 8 runs off the league and 2 standard errors clear of chance; Matches shows that as a pill. This season's games are checked daily as results come in, and flagged if they've moved at least 10 runs and 2 standard errors from the ground's usual. Reported pitch changes (re-laid squares, new drop-ins) are listed from `curated/venues.json`. It's background, not a predictor. Over 15 seasons, a ground's average has barely predicted its next season (slope 0.08 from the prior 5 seasons, 0.15 from last season alone), or even the second half of the same season (−0.06).
- **Roles**: club moves, batting-order shifts, newly opening, started or stopped bowling, and curated news. Shifts compare each player's last 3 games with their earlier games over the last 3 seasons.

## Alerts

Turn alerts on from the Matches page, for all matches or chosen teams (it suggests your squad's teams). They're Web Push notifications, so there's no app or account. On iPhone and iPad, add the site to the Home Screen first and turn alerts on from there (iOS 16.4 or later). For each league match it sends:

- **T-60**: start time, venue, rain risk from the forecast, and squad players who are unavailable that day.
- **XIs named**: both XIs, with captain and keeper marked, the squad players who were left out, and the toss result. It's sent once the cricket.com.au scorecard lists players, which happens at the toss.

`worker/` is a Cloudflare Worker that runs every minute and is the only thing that can send them: each push is signed with its VAPID key and encrypted to the subscriber (RFC 8291/8292, WebCrypto, no dependencies). It also takes subscriptions. It only accepts pages listed in `ORIGINS` and the Chrome, Firefox, Edge and Apple push services, and stores a subscription only after it accepts a confirmation push. An endpoint must be in its exact canonical form, so one subscription can't be stored twice; re-subscribing it with different keys is refused, and unsubscribing needs its `auth` secret.

A reminder whose window has already passed is skipped, not sent late. Each batch is recorded in KV as sent before it goes out, so a tick that fails part-way can lose an alert but never repeat one. A push that fails with a network error, 429 or 5xx is un-recorded and retried the next minute; a subscription the push service reports as gone is deleted. At most 20 pushes go out per minute (the free plan's 10 ms CPU limit); the rest follow a minute later.

Deploy:

```
cd worker
npx wrangler kv namespace create SENT   # paste the id into wrangler.toml
node -e "crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign']).then(k=>crypto.subtle.exportKey('jwk',k.privateKey)).then(j=>process.stdout.write(JSON.stringify(j)))" | npx wrangler secret put VAPID_PRIVATE
npx wrangler deploy
```

Changing `VAPID_PRIVATE` invalidates every subscription; subscribers have to turn alerts on again.

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
| Ground names in Cricsheet, pitch news | Hand-curated, keyed by CA venue id | `curated/venues.json`, `pipeline/venues.py` |

SC points are computed from the scorecards using `curated/scoring.json`. They're checked against SuperCoach's official BBL|15 league totals (`previous_total` in its player list): all 93 players' game counts agree, 76 totals are exact, and the rest are off by 199 points in 27,775. What's left is which fielder SuperCoach credits for a shared run-out, which follows no rule we can find, so Cricsheet's shared run-outs are split between the fielders. Byes and leg-byes are not dot balls. The live scorecard names one run-out fielder, who gets the full credit. Its dot count includes byes and leg-byes, so the live page subtracts them using the ball-by-ball commentary (`views/comments`), refetching only overs it hasn't seen. `logic.js` ports the scoring code, and a node test checks that it matches the Python on every 2025-26 line and on a replayed cricket.com.au scorecard. The Hundred uses 5-ball sets, so it gets no SC-equivalent; one-day and first-class get traditional stats only.

Cricsheet uses one person id across every competition, so squad players link without name matching. Newcomers with no BBL history are matched by name (exact, then initials) to the only namesake who has played in the last 3 years.

## SuperCoach snapshot

SuperCoach can't be fetched by a script, so each round, signed in at supercoach.com.au, save these responses into `curated/sc_raw/`. The quick way is the bookmark on [`tools.html`](https://donkalot.github.io/scbbl/tools.html): click it on any SuperCoach BBL page and it downloads all three files, already named, using your own login. By hand:

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
   - every fixture ground is in `curated/venues.json`, and every Cricsheet ground name this season maps to one
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
node --test tests/logic.test.js worker/test/notify.test.js worker/test/push.test.js   # logic.js, notifier, Web Push
```

To try the Worker locally, run `npx wrangler dev --test-scheduled --var SITE:<url>` and trigger a tick with `curl "http://localhost:8787/__scheduled?cron=*+*+*+*+*"`.

The smoke test needs `pip install -r tests/requirements.txt` and `playwright install chromium`.

## Layout

```
index.html, app.js   UI (hash router, no build step)
logic.js             pure functions shared by the UI and node tests
sw.js                network-first service worker (offline fallback, push notifications)
pipeline/            Python 3.12, standard library only
worker/              Web Push notifier and subscriptions (Cloudflare Worker, cron every minute)
curated/             hand-edited inputs
data/                generated, committed
```

## Support

If this helps your team, you can buy me a coffee at [ko-fi.com/donkware](https://ko-fi.com/donkware).
