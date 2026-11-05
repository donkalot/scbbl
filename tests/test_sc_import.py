import json
from collections import Counter

from pipeline import sc_import
from pipeline.common import CURATED, DATA

SQUADS = {'teams': {'SIX': [{'pid': 'od', 'n': 'Oliver Davies'}, {'pid': 'ss', 'n': 'Steve Smith'}],
                    'STR': [{'pid': 'ac', 'n': 'Alex Carey'}]}}


def _sc(first, last, team, **kw):
    return {'id': kw.get('id', 1), 'first_name': first, 'last_name': last, 'team': {'abbrev': team},
            'positions': [{'position': 'BAT', 'sort': 2}, {'position': 'WKP', 'sort': 1}],
            'previous_games': 3, 'previous_total': 166, 'injury_suspension_status': None,
            'player_stats': [{'round': 1, 'price': 137200, 'price_change': 0, 'owned': 2.56076,
                              'total_games': 0, 'total_points': 0, 'updated_at': '2026-10-23T00:42:08+11:00'}]}


def test_match_players_by_team_and_alias():
    got, problems = sc_import.match_players([_sc('Ollie', 'Davies', 'SY6'), _sc('Alex', 'Carey', 'ADL')], SQUADS, {})
    assert set(got) == {'od', 'ac'} and problems == []


def test_unknown_or_wrong_team_player_is_a_problem_until_mapped():
    _, problems = sc_import.match_players([_sc('Alex', 'Carey', 'SY6')], SQUADS, {})
    assert len(problems) == 1 and 'SIX Alex Carey' in problems[0]
    got, problems = sc_import.match_players([_sc('Steven', 'Smith', 'SY6')], SQUADS, {'Steven Smith': 'Steve Smith'})
    assert set(got) == {'ss'} and problems == []


def test_player_row():
    assert sc_import.player_row(_sc('Alex', 'Carey', 'ADL')) == {
        'id': 1, 'pos': ['WKP', 'BAT'], 'price': 137200, 'own': 2.6, 'prev': [3, 166]}


FIXTURE = [
    {'id': 1, 'stage': 'league', 'start': '2026-12-12T09:10:00Z', 'home': 'REN', 'away': 'SCO'},
    {'id': 2, 'stage': 'league', 'start': '2026-12-15T08:15:00Z', 'home': 'HEA', 'away': 'SIX'},
    {'id': 3, 'stage': 'final', 'start': '2027-01-26T08:15:00Z', 'home': None, 'away': None},
]


def _m(round_, kickoff, t1=None, t2=None):
    return {'round': round_, 'kickoff': kickoff, 'team1': t1 and {'abbrev': t1}, 'team2': t2 and {'abbrev': t2}}


def test_rounds_from_sc_fixture():
    sc = [_m(1, '2026-12-12T20:10:00+11:00', 'MLR', 'PER'), _m(1, '2026-12-15T19:15:00+11:00', 'BNE', 'SY6'),
          _m(9, '2027-01-26T19:15:00+11:00')]
    rounds, complete, problems = sc_import.rounds_from(sc, FIXTURE)
    assert problems == [] and complete
    assert rounds == [{'round': 1, 'start': '2026-12-12', 'end': '2026-12-15'},
                      {'round': 9, 'start': '2027-01-26', 'end': '2027-01-26', 'finals': True}]
    rounds, complete, _ = sc_import.rounds_from(sc[:2], FIXTURE)
    assert not complete and len(rounds) == 1


def test_rounds_reject_unmatched_and_overlapping():
    _, complete, problems = sc_import.rounds_from([_m(1, '2026-12-12T20:10:00+11:00', 'BNE', 'PER')], FIXTURE)
    assert not complete and 'has 0 CA fixture matches' in problems[0]
    _, _, problems = sc_import.rounds_from([_m(2, '2026-12-12T20:10:00+11:00', 'MLR', 'PER'),
                                            _m(1, '2026-12-15T19:15:00+11:00', 'BNE', 'SY6')], FIXTURE)
    assert problems == ['SC rounds 1 and 2 overlap (2026-12-15 / 2026-12-12)']


def test_our_points_reconcile_with_supercoach_2025_26_totals():
    """SuperCoach's previous_total is the official BBL|15 league total, the only real SC scores we have."""
    squads = json.loads((DATA / 'squads.json').read_text(encoding='utf-8'))
    sc_players = json.loads((CURATED / 'sc_raw' / 'players-round1.json').read_text(encoding='utf-8'))
    matched, problems = sc_import.match_players(sc_players, squads, {})
    assert problems == []
    ours = Counter()
    games = Counter()
    for m in json.loads((DATA / 'matches' / '2025-26.json').read_text(encoding='utf-8')):
        if m['final']:
            continue
        for l in m['lines']:
            if not l.get('sub'):
                ours[l['pid']] += l['sc']
                games[l['pid']] += 1
    played = {pid: p for pid, p in matched.items() if p['previous_games']}
    assert len(played) >= 90
    assert all(games[pid] == p['previous_games'] for pid, p in played.items())
    diffs = [ours[pid] - p['previous_total'] for pid, p in played.items()]
    # What's left is which fielder SuperCoach credits for a shared run-out, plus a stray catch.
    assert sum(d == 0 for d in diffs) >= 76
    assert sum(map(abs, diffs)) <= 200
