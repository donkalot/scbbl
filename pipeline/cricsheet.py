import io
import json
import time
import zipfile
from collections import defaultdict

from .common import CACHE, fetch, team_code

ZIP_URL = 'https://cricsheet.org/downloads/bbl_json.zip'
BOWLER_WICKETS = {'bowled', 'caught', 'caught and bowled', 'lbw', 'stumped', 'hit wicket'}
NOT_OUT_KINDS = {'retired hurt', 'retired not out'}


def load_zip(max_age_h=12):
    path = CACHE / 'bbl_json.zip'
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_h * 3600:
        CACHE.mkdir(exist_ok=True)
        path.write_bytes(fetch(ZIP_URL))
    return zipfile.ZipFile(io.BytesIO(path.read_bytes()))


def iter_matches(z):
    for n in sorted(z.namelist()):
        if n.endswith('.json'):
            yield n.removesuffix('.json'), json.loads(z.read(n))


def _blank():
    return {'bat_pos': None, 'r': 0, 'bf': 0, 'f4': 0, 's6': 0, 'out': False, 'how': None,
            'lb': 0, 'rc': 0, 'wk': 0, 'dots': 0, 'mdn': 0, 'wd': 0, 'nb': 0,
            'ct': 0, 'st': 0, 'ro': 0, 'ro_solo': 0, 'batted': False, 'bowled': False}


def parse_match(mid, d):
    """One line per XI player: batting, bowling and fielding totals for the match."""
    info = d['info']
    reg = info['registry']['people']
    teams = info['teams']
    lines = {}
    for team in teams:
        opp = teams[1] if team == teams[0] else teams[0]
        for name in info['players'][team]:
            lines[name] = {'pid': reg[name], 'name': name, 'team': team_code(team), 'opp': team_code(opp),
                           **_blank()}

    def get(name):
        # Substitute fielders are not in info.players but still take catches.
        if name not in lines:
            lines[name] = {'pid': reg.get(name), 'name': name, 'team': None, 'opp': None, 'sub': True,
                           **_blank()}
        return lines[name]

    for inn in d['innings']:
        if inn.get('super_over'):
            continue
        order = []
        for over in inn['overs']:
            per_bowler = defaultdict(lambda: [0, 0])  # legal balls, runs conceded
            for dl in over['deliveries']:
                for who in (dl['batter'], dl['non_striker']):
                    if who not in order:
                        order.append(who)
                ex = dl.get('extras', {})
                wide, nb = ex.get('wides', 0), ex.get('noballs', 0)
                bat = get(dl['batter'])
                bat['batted'] = True
                bat['r'] += dl['runs']['batter']
                if not wide:
                    bat['bf'] += 1
                if dl['runs']['batter'] == 4 and not dl['runs'].get('non_boundary'):
                    bat['f4'] += 1
                elif dl['runs']['batter'] == 6:
                    bat['s6'] += 1
                get(dl['non_striker'])['batted'] = True

                bwl = get(dl['bowler'])
                bwl['bowled'] = True
                conceded = dl['runs']['batter'] + wide + nb
                bwl['rc'] += conceded
                bwl['wd'] += 1 if wide else 0
                bwl['nb'] += 1 if nb else 0
                legal = not wide and not nb
                if legal:
                    bwl['lb'] += 1
                    if conceded == 0:
                        bwl['dots'] += 1
                pb = per_bowler[dl['bowler']]
                pb[0] += 1 if legal else 0
                pb[1] += conceded

                for w in dl.get('wickets', []):
                    kind = w['kind']
                    out = get(w['player_out'])
                    out['batted'] = True
                    if w['player_out'] not in order:
                        order.append(w['player_out'])
                    if kind not in NOT_OUT_KINDS:
                        out['out'] = True
                        out['how'] = kind
                    if kind in BOWLER_WICKETS:
                        bwl['wk'] += 1
                    fielders = [f['name'] for f in w.get('fielders', []) if 'name' in f]
                    if kind == 'caught' and fielders:
                        get(fielders[0])['ct'] += 1
                    elif kind == 'caught and bowled':
                        bwl['ct'] += 1
                    elif kind == 'stumped' and fielders:
                        get(fielders[0])['st'] += 1
                    elif kind == 'run out':
                        for f in fielders:
                            get(f)['ro'] += 1
                        if len(fielders) == 1:
                            get(fielders[0])['ro_solo'] += 1
            for name, (legal_balls, conceded) in per_bowler.items():
                if legal_balls == 6 and conceded == 0:
                    lines[name]['mdn'] += 1
        for pos, name in enumerate(order, 1):
            lines[name]['bat_pos'] = pos

    meta = {
        'id': mid,
        'season': str(info['season']),
        'date': info['dates'][0],
        'venue': info.get('venue'),
        'city': info.get('city'),
        'teams': [team_code(t) for t in teams],
        'result': _result(info.get('outcome', {})),
        'final': 'stage' in info.get('event', {}) and info['event']['stage'] != 'group',
    }
    return meta, list(lines.values())


def _result(o):
    if 'winner' in o:
        return {'winner': team_code(o['winner'])}
    return {'result': o.get('result', 'unknown')}


def parse_all(z):
    by_season = defaultdict(list)
    for mid, d in iter_matches(z):
        meta, lines = parse_match(mid, d)
        by_season[meta['season']].append({**meta, 'lines': lines})
    for matches in by_season.values():
        matches.sort(key=lambda m: (m['date'], m['id']))
    return dict(by_season)
