import json
import sys

from .common import DATA

BASELINE = DATA / 'baseline.json'
MAX_PLAYER_DROP = 0.25


def check_history(by_season, players, baseline):
    problems = []
    for season, n in baseline.get('season_matches', {}).items():
        got = len(by_season.get(season, []))
        if got < n:
            problems.append(f'season {season}: {got} matches, baseline {n}')
    base_players = baseline.get('players', 0)
    if base_players and len(players) < base_players * (1 - MAX_PLAYER_DROP):
        problems.append(f'{len(players)} players, more than {MAX_PLAYER_DROP:.0%} below baseline {base_players}')
    return problems


def ratchet(by_season, players, baseline):
    """Baselines only ever rise, so a source that shrinks is caught on the next run."""
    seasons = dict(baseline.get('season_matches', {}))
    for season, ms in by_season.items():
        seasons[season] = max(seasons.get(season, 0), len(ms))
    return {'season_matches': dict(sorted(seasons.items())),
            'players': max(baseline.get('players', 0), len(players))}


def load_baseline():
    return json.loads(BASELINE.read_text()) if BASELINE.exists() else {}


def fail_if(problems, source):
    if problems:
        for p in problems:
            print(f'GUARD [{source}] {p}', file=sys.stderr)
        sys.exit(1)
