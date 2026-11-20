import io
import json
import os
import time
import urllib.error
import zipfile
from pathlib import Path

import pytest

from pipeline import cricsheet
from pipeline.cricsheet import parse_match

FX = Path(__file__).parent / 'fixtures'


def _cs_vs_ca():
    d = json.loads((FX / 'cricsheet_1493243.json').read_text())
    _, lines = parse_match('1493243', d)
    ca = json.loads((FX / 'ca_scorecard_23768.json').read_text())
    pname = {p['id']: p['displayName'].split()[-1].lower() for p in ca['players']}
    cs = {l['name'].split()[-1].lower(): l for l in lines}
    return lines, cs, ca, pname


def test_batting_matches_official_scorecard():
    _, cs, ca, pname = _cs_vs_ca()
    for inn in ca['fixture']['innings']:
        for b in inn['batsmen']:
            l = cs[pname[b['playerId']]]
            if 'runsScored' not in b:
                assert not l['batted']
                continue
            assert (l['r'], l['bf'], l['f4'], l['s6'], l['bat_pos'], l['out']) == (
                b['runsScored'], b['ballsFaced'], b['foursScored'], b['sixesScored'], b['battingOrder'], b['isOut'])


def test_bowling_matches_official_scorecard():
    _, cs, ca, pname = _cs_vs_ca()
    d = json.loads((FX / 'cricsheet_1493243.json').read_text())
    bye_balls = {}
    for inn in d['innings']:
        for over in inn['overs']:
            for dl in over['deliveries']:
                ex = dl.get('extras', {})
                if (ex.get('byes') or ex.get('legbyes')) and not (dl['runs']['batter'] or ex.get('wides') or ex.get('noballs')):
                    key = dl['bowler'].split()[-1].lower()
                    bye_balls[key] = bye_balls.get(key, 0) + 1
    assert sum(bye_balls.values()) > 0
    for inn in ca['fixture']['innings']:
        for w in inn['bowlers']:
            key = pname[w['playerId']]
            l = cs[key]
            # cricket.com.au counts byes and leg-byes as dots; SuperCoach (and our lines) don't.
            assert (l['lb'], l['rc'], l['wk'], l['dots'] + bye_balls.get(key, 0), l['mdn'], l['wd'], l['nb']) == (
                w['totalBallsBowled'], w['runsConceded'], w['wicketsTaken'], w['dotBalls'],
                w['maidensBowled'], w['wideBalls'], w['noBalls'])


def test_fielding_credits_and_substitutes():
    lines, cs, _, _ = _cs_vs_ca()
    assert cs['bartlett']['ct'] == 2
    # Cricsheet credits both run-out fielders; cricket.com.au credits only one (Evans).
    assert cs['evans']['ro'] == 1 and cs['allen']['ro'] == 1 and cs['evans']['ro_solo'] == 0
    sub = [l for l in lines if l.get('sub')]
    assert [s['name'] for s in sub] == ['Thomas Balkin'] and sub[0]['ct'] == 1


def _match(deliveries, super_over=None):
    names = ['A', 'B', 'C', 'X', 'Y']
    d = {'info': {'teams': ['Brisbane Heat', 'Perth Scorchers'], 'season': '2025/26', 'dates': ['2025-12-19'],
                  'players': {'Brisbane Heat': ['A', 'B', 'C'], 'Perth Scorchers': ['X', 'Y']},
                  'registry': {'people': {n: n.lower() for n in names}}, 'outcome': {'result': 'no result'}},
         'innings': [{'team': 'Brisbane Heat', 'overs': [{'over': 0, 'deliveries': deliveries}]}]}
    if super_over:
        d['innings'].append({'team': 'Brisbane Heat', 'super_over': True,
                             'overs': [{'over': 0, 'deliveries': super_over}]})
    return {l['name']: l for l in parse_match('t', d)[1]}


def _dl(runs=0, extras=None, batter='A', wickets=None, non_boundary=False):
    d = {'batter': batter, 'bowler': 'X', 'non_striker': 'B' if batter == 'A' else 'A',
         'runs': {'batter': runs, 'extras': sum((extras or {}).values()), 'total': runs + sum((extras or {}).values())}}
    if extras:
        d['extras'] = extras
    if wickets:
        d['wickets'] = wickets
    if non_boundary:
        d['runs']['non_boundary'] = True
    return d


def test_maiden_needs_six_legal_scoreless_balls():
    assert _match([_dl() for _ in range(6)])['X']['mdn'] == 1
    lb = _match([_dl() for _ in range(5)] + [_dl(extras={'legbyes': 1})])['X']
    assert lb['mdn'] == 1 and lb['dots'] == 5
    assert _match([_dl() for _ in range(6)] + [_dl(extras={'wides': 1})])['X']['mdn'] == 0


def test_wides_not_faced_noballs_faced_non_boundary_four():
    l = _match([_dl(extras={'wides': 1}), _dl(1, {'noballs': 1}), _dl(4, non_boundary=True)])
    assert l['A']['bf'] == 2 and l['A']['f4'] == 0 and l['A']['r'] == 5
    assert l['X']['rc'] == 7 and l['X']['lb'] == 1 and l['X']['wd'] == 1 and l['X']['nb'] == 1


def test_run_out_not_bowler_wicket_and_non_striker_gets_position():
    w = [{'player_out': 'C', 'kind': 'run out', 'fielders': [{'name': 'Y'}]}]
    l = _match([_dl(), _dl(wickets=w)])
    assert l['X']['wk'] == 0 and l['Y']['ro_solo'] == 1
    assert l['C']['out'] and l['C']['bat_pos'] == 3


def test_retired_hurt_is_not_out_and_super_over_ignored():
    w = [{'player_out': 'A', 'kind': 'retired hurt'}]
    l = _match([_dl(wickets=w)], super_over=[_dl(6) for _ in range(6)])
    assert not l['A']['out'] and l['A']['r'] == 0 and l['A']['s6'] == 0


def test_innings_totals_match_official_scorecard():
    d = json.loads((FX / 'cricsheet_1493243.json').read_text())
    meta, _ = parse_match('1493243', d)
    ca = json.loads((FX / 'ca_scorecard_23768.json').read_text())
    overs = lambda s: int(s.split('.')[0]) * 6 + int(s.split('.')[1])
    assert [(i['runs'], i['balls'], i['wk']) for i in meta['inns']] == [
        (i['runsScored'], overs(i['oversBowled']), i['numberOfWicketsFallen']) for i in ca['fixture']['innings']]


def _zip_bytes(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(f'{name}.json', '{}')
    return buf.getvalue()


def _cache(tmp_path, monkeypatch, age_h, fetch):
    monkeypatch.setattr(cricsheet, 'CACHE', tmp_path)
    monkeypatch.setattr(cricsheet, 'fetch', fetch)
    p = tmp_path / 'bbl_json.zip'
    p.unlink(missing_ok=True)
    if age_h is not None:
        p.write_bytes(_zip_bytes('old'))
        t = time.time() - age_h * 3600
        os.utime(p, (t, t))


def _refused(url):
    raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)


def _not_called(url):
    raise AssertionError('refetched a fresh cache')


def test_a_refused_download_falls_back_to_a_recent_cached_zip(tmp_path, monkeypatch, capsys):
    _cache(tmp_path, monkeypatch, 30, _refused)
    assert cricsheet.load_zip().namelist() == ['old.json']
    assert '::warning::Cricsheet download failed' in capsys.readouterr().out


def test_a_refused_download_still_fails_with_no_cache_or_an_old_one(tmp_path, monkeypatch):
    for age in (None, 100):
        _cache(tmp_path, monkeypatch, age, _refused)
        with pytest.raises(urllib.error.HTTPError):
            cricsheet.load_zip()


def test_a_download_replaces_a_day_old_cache_and_a_fresh_one_is_not_refetched(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch, 30, lambda url: _zip_bytes('new'))
    assert cricsheet.load_zip().namelist() == ['new.json']
    monkeypatch.setattr(cricsheet, 'fetch', _not_called)
    assert cricsheet.load_zip().namelist() == ['new.json']


def test_a_page_that_is_not_a_zip_is_treated_as_refused_and_never_overwrites_the_cache(tmp_path, monkeypatch, capsys):
    challenge = lambda url: b'<html>Just a moment...</html>'
    _cache(tmp_path, monkeypatch, 30, challenge)
    assert cricsheet.load_zip().namelist() == ['old.json']
    assert 'not a zip' in capsys.readouterr().out
    _cache(tmp_path, monkeypatch, None, challenge)
    with pytest.raises(OSError, match='not a zip'):
        cricsheet.load_zip()
    assert not (tmp_path / 'bbl_json.zip').exists()


def test_max_age_zero_refetches_even_a_fresh_cache(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch, 0.1, lambda url: _zip_bytes('new'))
    assert cricsheet.load_zip(max_age_h=0).namelist() == ['new.json']
