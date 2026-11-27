import io
import os
import time
import urllib.error
import zipfile

import pytest

from pipeline import elsewhere
from pipeline.cricsheet import parse_match

NAMES = ['A', 'B', 'X', 'Y']


def _d(batter, bowler, non_striker, runs=0, out=None):
    d = {'batter': batter, 'bowler': bowler, 'non_striker': non_striker,
         'runs': {'batter': runs, 'extras': 0, 'total': runs}}
    if out:
        d['wickets'] = [{'player_out': out, 'kind': 'bowled'}]
    return d


def _inn(team, deliveries):
    return {'team': team, 'overs': [{'over': 0, 'deliveries': deliveries}]}


def _shield(date='2026-10-20'):
    """Two innings each: A falls for 8 then makes 60*; B never faces in the first innings."""
    first = [_d('A', 'X', 'B', 4), _d('A', 'X', 'B', 4), _d('A', 'X', 'B', out='A')]
    third = [_d('A', 'Y', 'B', 6) for _ in range(10)]
    second = [_d('X', 'A', 'Y', 1), _d('X', 'A', 'Y', out='X')]
    d = {'info': {'teams': ['Queensland', 'Victoria'], 'season': '2026/27', 'dates': [date],
                  'match_type': 'MDM',
                  'players': {'Queensland': ['A', 'B'], 'Victoria': ['X', 'Y']},
                  'registry': {'people': {n: n.lower() for n in NAMES}}, 'outcome': {'result': 'draw'}},
         'innings': [_inn('Queensland', first), _inn('Victoria', second), _inn('Queensland', third)]}
    return parse_match('s1', d, code=lambda t: t)


def _lines():
    return {l['name']: l for l in _shield()[1]}


def test_two_innings_give_per_innings_batting_and_bowling():
    l = _lines()
    assert l['A']['bi'] == [[8, 3, True], [60, 10, False]]
    assert l['B']['bi'] == [[0, 0, False], [0, 0, False]]
    assert l['X']['wi'] == [[3, 8, 1]]
    assert l['A']['wi'] == [[2, 1, 1]]


def test_aggregate_counts_innings_not_outs_and_high_score():
    l = _lines()
    a = elsewhere._agg()
    elsewhere.add(a, l['A'])
    assert (a['m'], a['inn'], a['no'], a['r'], a['hs'], a['hsn'], a['f50']) == (1, 2, 1, 68, 60, True, 1)
    assert a['bb'] == [1, 1] and 'sc' not in a and 'scm' not in a


def test_best_bowling_prefers_wickets_then_fewer_runs():
    a = elsewhere._agg()
    for wi in ([[24, 30, 2]], [[24, 20, 2]], [[24, 50, 1]]):
        elsewhere.add(a, {**{k: 0 for k in elsewhere.STATS}, 'bi': [], 'wi': wi})
    assert a['bb'] == [2, 20]


def test_sc_equivalent_only_for_sc_competitions(monkeypatch):
    _, raw = _shield()
    match = {'info': {}, 'innings': []}
    monkeypatch.setattr(elsewhere, 'load', lambda code: code)
    monkeypatch.setattr(elsewhere, 'iter_matches', lambda z: [('m1', match)])
    monkeypatch.setattr(elsewhere, 'parse_match', lambda mid, d, code: _shield())
    cc = [{'code': 'hnd', 'g': 't20'}, {'code': 'ipl', 'g': 't20', 'sc': True}]
    found, counts = elsewhere.collect({'a'}, [], '2026-01-01', cc)
    assert counts == {'hnd': 1, 'ipl': 1}
    c = found['a']['c']
    assert 'sc' not in c['hnd']['2026/27'] and c['ipl']['2026/27']['scm'] == 1
    assert found['a']['y']['t20']['m'] == 2 and found['a']['y']['t20']['scm'] == 1
    assert [('sc' in g) for g in found['a']['f']] == [False, True]
    assert 'x' not in found  # not a squad player and not a possible newcomer


def test_newcomer_resolves_to_the_only_recent_namesake():
    found = {'jb1': {'n': 'JM Bairstow', 'last': '2026-08-01'},
             'jb0': {'n': 'JA Bairstow', 'last': '2012-01-01'},
             'k1': {'n': 'Known Player', 'last': '2026-08-01'}}
    r = {'n': 'Jonny Bairstow', 'pid': 'new-jonny-bairstow', 'new': True}
    assert elsewhere.resolve([r], found, {'k1'}, '2023-11-01') == []
    assert (r['pid'], r['cs']) == ('jb1', 'JM Bairstow')


def test_exact_name_beats_initials_and_two_recent_namesakes_stay_unresolved():
    found = {'s1': {'n': 'Jake Scott', 'last': '2026-01-01'},
             's2': {'n': 'J Scott', 'last': '2026-01-01'}}
    r = {'n': 'Jake Scott', 'pid': 'new-jake-scott', 'new': True}
    assert elsewhere.resolve([r], found, set(), '2023-11-01') == [] and r['pid'] == 's1'

    found = {'t1': {'n': 'T Robinson', 'last': '2026-01-01'}, 't2': {'n': 'TJ Robinson', 'last': '2025-06-01'}}
    r = {'n': 'Tim Robinson', 'pid': 'new-tim-robinson', 'new': True}
    [msg] = elsewhere.resolve([r], found, set(), '2023-11-01')
    assert 'ambiguous' in msg and r['pid'] == 'new-tim-robinson'


def test_check_flags_shrunken_competition_and_poor_linking():
    base = {'comp_matches': {'ssh': 218, 'ipl': 1243}}
    known = {f'p{i}' for i in range(20)}
    found = {f'p{i}': {} for i in range(19)}
    assert elsewhere.check({'ssh': 218, 'ipl': 1243}, found, known, base) == []
    problems = elsewhere.check({'ssh': 200}, {}, known, base)
    assert problems == ['ssh: 200 matches, baseline 218', 'ipl: 0 matches, baseline 1243',
                        'only 0 of 20 squad players have a record outside the BBL']


def test_attach_form_gives_squad_rows_their_scored_t20_games():
    sq = {'teams': {'HEA': [{'pid': 'a'}, {'pid': 'b'}, {'pid': 'c'}, {'n': 'Unresolved'}]}}
    ew = {'players': {'a': {'y': {'t20': {'m': 9, 'sc': 400, 'scm': 8}, 'od': {'m': 3}}},
                      'b': {'y': {'t20': {'m': 2}}}, 'c': {'y': {'fc': {'m': 4}}}}}
    elsewhere.attach_form(sq, ew)
    assert [r.get('f20') for r in sq['teams']['HEA']] == [[400, 8], None, None, None]


def test_load_refuses_a_code_that_is_not_a_plain_name(monkeypatch):
    monkeypatch.setattr(elsewhere, 'fetch', lambda url: pytest.fail('fetched'))
    for code in ('../../x', 'C:/x', 'ipl/../x', 'IPL'):
        with pytest.raises(ValueError):
            elsewhere.load(code)


def _build(monkeypatch, cached, fresh, refuse=()):
    """collect() counts the cached zips until load(max_age_h=0) has refreshed them."""
    state = {'fresh': set(), 'collects': 0}
    monkeypatch.setattr(elsewhere, 'comps', lambda: [{'code': 'ssh', 'g': 'fc'}, {'code': 'ipl', 'g': 't20'}])

    def load(code, max_age_h=elsewhere.MAX_AGE_H, stale_ok=True):
        assert max_age_h == 0 and not stale_ok
        if code in refuse:
            raise urllib.error.HTTPError('u', 403, 'Forbidden', {}, None)
        state['fresh'].add(code)

    def collect(known, newcomers, since, cc):
        state['collects'] += 1
        return {'a': {}}, {c['code']: (fresh if c['code'] in state['fresh'] else cached)[c['code']] for c in cc}

    monkeypatch.setattr(elsewhere, 'load', load)
    monkeypatch.setattr(elsewhere, 'collect', collect)
    sq = {'teams': {'HEA': [{'pid': 'a'}]}}
    _, counts, _, problems = elsewhere.build(sq, {'comp_matches': {'ssh': 222, 'ipl': 1243}})
    return counts, problems, state


def test_a_cache_older_than_the_baseline_is_refetched_before_it_counts_as_shrunk(monkeypatch):
    counts, problems, state = _build(monkeypatch, {'ssh': 218, 'ipl': 1243}, {'ssh': 222, 'ipl': 1243})
    assert problems == [] and counts == {'ssh': 222, 'ipl': 1243}
    assert state['fresh'] == {'ssh'} and state['collects'] == 2


def test_a_fresh_copy_that_is_still_short_fails(monkeypatch):
    _, problems, _ = _build(monkeypatch, {'ssh': 218, 'ipl': 1243}, {'ssh': 220, 'ipl': 1243})
    assert problems == ['ssh: 220 matches, baseline 222']


def test_a_refused_refetch_of_a_short_cache_fails_and_says_why(monkeypatch):
    _, problems, state = _build(monkeypatch, {'ssh': 218, 'ipl': 1243}, {}, refuse={'ssh'})
    assert problems == ['ssh: the cached copy is short and a fresh download failed (HTTP Error 403: Forbidden)',
                        'ssh: 218 matches, baseline 222']
    assert state['collects'] == 1


def test_one_refused_refetch_does_not_stop_another_from_counting(monkeypatch):
    counts, problems, state = _build(monkeypatch, {'ssh': 218, 'ipl': 1200}, {'ssh': 222, 'ipl': 1243}, refuse={'ipl'})
    assert counts == {'ssh': 222, 'ipl': 1200} and state['collects'] == 2
    assert problems == ['ipl: the cached copy is short and a fresh download failed (HTTP Error 403: Forbidden)',
                        'ipl: 1200 matches, baseline 1243']


def test_a_cache_at_the_baseline_is_not_refetched(monkeypatch):
    _, problems, state = _build(monkeypatch, {'ssh': 222, 'ipl': 1300}, {})
    assert problems == [] and state['fresh'] == set() and state['collects'] == 1


def _zip_cache(tmp_path, monkeypatch, fetch, age_h=200):
    monkeypatch.setattr(elsewhere, 'DIR', tmp_path)
    monkeypatch.setattr(elsewhere, 'fetch', fetch)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('old.json', '{}')
    p = tmp_path / 'ssh_male_json.zip'
    p.write_bytes(buf.getvalue())
    t = time.time() - age_h * 3600
    os.utime(p, (t, t))


def _refused(url):
    raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)


def test_a_refused_weekly_refetch_uses_the_cached_zip_but_a_forced_one_raises(tmp_path, monkeypatch, capsys):
    _zip_cache(tmp_path, monkeypatch, _refused)
    assert elsewhere.load('ssh').namelist() == ['old.json']
    assert '::warning::ssh download failed' in capsys.readouterr().out
    with pytest.raises(urllib.error.HTTPError):
        elsewhere.load('ssh', max_age_h=0, stale_ok=False)
    (tmp_path / 'ssh_male_json.zip').unlink()
    with pytest.raises(urllib.error.HTTPError):
        elsewhere.load('ssh')


def test_load_treats_a_page_that_is_not_a_zip_as_refused_and_keeps_the_cache(tmp_path, monkeypatch):
    _zip_cache(tmp_path, monkeypatch, lambda url: b'<html>Just a moment...</html>')
    with pytest.raises(OSError, match='not a zip'):
        elsewhere.load('ssh', max_age_h=0, stale_ok=False)
    assert elsewhere.load('ssh').namelist() == ['old.json']
