import json
from collections import Counter
from datetime import date

from .common import CURATED, ca, team_code

COMPETITION_ID = 4691  # KFC BBL|16
LEAGUE_MATCHES = 40
PER_TEAM = 10
WINDOW = (date(2026, 12, 12), date(2027, 1, 18))


def fetch_raw():
    return ca('fixtures/yearfilter', competitionId=COMPETITION_ID, limit=60, isInningInclude='true')['fixtures']


def normalise(raw, overrides=None):
    overrides = overrides or {}
    out = []
    for f in raw:
        home, away = f['homeTeam']['shortName'], f['awayTeam']['shortName']
        league = f['name'].startswith('Match ')
        v = f.get('venue')
        m = {
            'id': f['id'],
            'name': f['name'],
            'stage': 'league' if league else 'final',
            'start': f['startDateTime'],
            'end': f['endDateTime'],
            'home': team_code(f['homeTeam']['name']) if league else home,
            'away': team_code(f['awayTeam']['name']) if league else away,
            'venue': {'id': v['id'], 'name': v['name'], 'city': v.get('location') or v.get('city'),
                      'lat': float(v['latitude']), 'lon': float(v['longitude'])} if v else None,
        }
        m.update(overrides.get(str(f['id']), {}))
        out.append(m)
    out.sort(key=lambda m: m['start'])
    return out


def check(matches):
    """Return a list of problems; empty means the fixture is safe to publish."""
    problems = []
    league = [m for m in matches if m['stage'] == 'league']
    if len(league) != LEAGUE_MATCHES:
        problems.append(f'{len(league)} league matches, expected {LEAGUE_MATCHES}')
    games = Counter(t for m in league for t in (m['home'], m['away']))
    for team, n in sorted(games.items()):
        if n != PER_TEAM:
            problems.append(f'{team} has {n} league matches, expected {PER_TEAM}')
    per_day = Counter((m['start'][:10], t) for m in league for t in (m['home'], m['away']))
    problems += [f'{t} plays twice on {d}' for (d, t), n in per_day.items() if n > 1]
    for m in league:
        d = date.fromisoformat(m['start'][:10])
        if not WINDOW[0] <= d <= WINDOW[1]:
            problems.append(f"{m['name']} ({m['id']}) dated {d}, outside {WINDOW[0]}..{WINDOW[1]}")
        if m['home'] == m['away']:
            problems.append(f"{m['name']} has {m['home']} playing itself")
    return problems


def build():
    path = CURATED / 'fixture_overrides.json'
    overrides = json.loads(path.read_text()) if path.exists() else {}
    return normalise(fetch_raw(), overrides)
