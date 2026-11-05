import json
from pathlib import Path

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
