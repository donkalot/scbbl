import json
from datetime import date, timedelta

import pytest

from pipeline import fixture, guards, squads
from pipeline.common import CURATED

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


def test_finals_awaiting_teams_pass():
    fx = _league() + [{'id': 99, 'name': 'The Final', 'stage': 'final', 'home': 'TBC', 'away': 'TBC',
                       'start': '2027-01-26T08:15:00Z'}]
    assert fixture.check(fx) == []


@pytest.mark.parametrize('field, value', [
    ('home', '<img src=x onerror=alert(1)>'), ('away', 'Heat'), ('id', '1" onclick="x'), ('id', True),
])
def test_values_the_site_shows_unescaped_must_be_plain(field, value):
    fx = _league()
    fx[0][field] = value
    assert any(repr(value) in p for p in fixture.check(fx))


def test_valid_rounds_pass():
    assert fixture.check_rounds({'rounds': [{'round': 1, 'start': '2026-12-12', 'end': '2026-12-19'},
                                            {'round': 10, 'start': '2027-01-19', 'end': '2027-01-26',
                                             'finals': True}]}) == []


@pytest.mark.parametrize('row', [
    {'round': '1<script>', 'start': '2026-12-12', 'end': '2026-12-19'},
    {'round': 1.0, 'start': '2026-12-12', 'end': '2026-12-19'},
    {'round': 1, 'start': '2026-12-12"><b>', 'end': '2026-12-19'},
    {'round': 1, 'start': '2026-12-12', 'end': '20261219'},
    {'round': 1, 'start': '"><b>x</b>', 'end': '2026-12-19'},
    {'round': 1, 'start': '2026-W50-1', 'end': '2026-12-19'},
    {'round': 1, 'start': 20261212, 'end': '2026-12-19'},
    {'round': 1, 'start': '2026-12-12'},
])
def test_bad_rounds_are_caught(row):
    assert fixture.check_rounds({'rounds': [row]})


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
    baseline['comp_matches'] = {'ssh': 218}
    raised = guards.ratchet({'2024/25': [{}] * 43, '2025/26': [{}] * 44}, {i: 0 for i in range(299)}, baseline,
                            {'ssh': 210, 'hnd': 201})
    assert raised == {'season_matches': {'2024/25': 44, '2025/26': 44}, 'players': 400,
                      'comp_matches': {'hnd': 201, 'ssh': 218}}


def _avail(**link):
    return {'events': [{'id': 's', 'start': '2026-12-09', 'end': '2027-01-08'}],
            'links': [{'team': 'SIX', 'player': 'Steve Smith', 'event': 's', **link}]}


def test_curated_availability_passes():
    assert squads.check_availability(json.loads((CURATED / 'availability.json').read_text(encoding='utf-8'))) == []


@pytest.mark.parametrize('link', [{}, {'until': '2026-12-13'}, {'from': '2026-12-17'},
                                  {'from': '2026-12-09', 'until': '2027-01-08'}, {'from': '2026-12-20', 'until': '2026-12-20'}])
def test_good_links_pass(link):
    assert squads.check_availability(_avail(**link)) == []


@pytest.mark.parametrize('link', [
    {'event': 'nope'}, {'until': '2027-01-09'}, {'from': '2026-12-08'}, {'from': '2026-12-20', 'until': '2026-12-19'},
    {'until': '13 Dec'}, {'until': '2026-12-1'}, {'from': 20261217}, {'until': None},
])
def test_bad_links_are_caught(link):
    assert squads.check_availability(_avail(**link))


@pytest.mark.parametrize('event', [{'start': '2027-01-09'}, {'end': '9 Jan'}, {'start': None}, {'start': 20261209}])
def test_bad_event_dates_are_caught_without_crashing(event):
    a = _avail(**{'from': '2026-12-17'})
    a['events'][0].update(event)
    assert any("event 's' dates" in p for p in squads.check_availability(a))


def test_duplicate_event_ids_are_caught():
    a = _avail()
    a['events'].append(dict(a['events'][0]))
    assert squads.check_availability(a)
