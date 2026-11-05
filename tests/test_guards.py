from datetime import date, timedelta

from pipeline import fixture, guards

TEAMS = ['HEA', 'HUR', 'REN', 'SCO', 'SIX', 'STA', 'STR', 'THU']


def _league():
    """40 matches, 10 per team (circle-method round robin, first 3 rounds repeated), one match per day."""
    rounds = []
    for r in range(7):
        ring = TEAMS[1:][r:] + TEAMS[1:][:r]
        rounds.append([(TEAMS[0], ring[0])] + [(ring[i], ring[7 - i]) for i in range(1, 4)])
    pairs = [p for rnd in rounds + rounds[:3] for p in rnd]
    day0 = date(2026, 12, 12)
    return [{'id': i, 'name': f'Match {i + 1}', 'stage': 'league', 'home': h, 'away': a,
             'start': f'{day0 + timedelta(days=i // 2)}T08:15:00Z'} for i, (h, a) in enumerate(pairs)]


def test_valid_fixture_passes():
    assert fixture.check(_league()) == []


def test_missing_match_is_caught():
    problems = fixture.check(_league()[:-1])
    assert '39 league matches, expected 40' in problems
    assert any('has 9 league matches' in p for p in problems)


def test_out_of_window_date_is_caught():
    fx = _league()
    fx[0]['start'] = '2026-07-10T08:15:00Z'
    assert any('outside' in p and 'Match 1 ' in p for p in fixture.check(fx))


def test_team_twice_in_a_day_is_caught():
    fx = _league()
    fx[4]['start'] = fx[0]['start']
    shared = {fx[0]['home'], fx[0]['away']} & {fx[4]['home'], fx[4]['away']}
    assert shared and any('plays twice' in p for p in fixture.check(fx))


def test_overrides_fix_a_bad_row():
    raw = [{'id': 1, 'name': 'Match 1', 'startDateTime': '2026-07-10T09:10:00Z', 'endDateTime': 'x',
            'homeTeam': {'name': 'Brisbane Heat', 'shortName': 'HEA'},
            'awayTeam': {'name': 'Perth Scorchers', 'shortName': 'SCO'}}]
    m = fixture.normalise(raw, {'1': {'start': '2026-12-12T09:10:00Z'}})[0]
    assert (m['home'], m['away'], m['start'], m['venue']) == ('HEA', 'SCO', '2026-12-12T09:10:00Z', None)


def test_shrunken_source_fails_and_baseline_only_rises():
    baseline = {'season_matches': {'2024/25': 44}, 'players': 400}
    assert guards.check_history({'2024/25': [{}] * 44}, {i: 0 for i in range(400)}, baseline) == []
    problems = guards.check_history({'2024/25': [{}] * 43}, {i: 0 for i in range(299)}, baseline)
    assert len(problems) == 2
    raised = guards.ratchet({'2024/25': [{}] * 43, '2025/26': [{}] * 44}, {i: 0 for i in range(299)}, baseline)
    assert raised == {'season_matches': {'2024/25': 44, '2025/26': 44}, 'players': 400}
