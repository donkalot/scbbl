import json
from datetime import datetime, timezone

from . import cricsheet, fixture, guards, register, roles, squads
from .common import CURATED, DATA, write_json
from .scoring import sc_points

SEASON_STATS = ('r', 'bf', 'f4', 's6', 'lb', 'rc', 'wk', 'dots', 'mdn', 'ct', 'st', 'ro')


def season_file(season):
    return season.replace('/', '-')


def aggregate(by_season, names):
    players = {}
    for season, ms in by_season.items():
        for m in ms:
            for l in m['lines']:
                if l.get('sub') or not l['pid']:
                    continue
                p = players.setdefault(l['pid'], {'n': names.get(l['pid'], l['name']), 's': {}})
                a = p['s'].setdefault(season, {'t': l['team'], 'm': 0, 'inn': 0, 'no': 0, 'hs': 0,
                                               'fifty': 0, 'hund': 0, 'sc': 0, **{k: 0 for k in SEASON_STATS}})
                a['m'] += 1
                a['sc'] += sc_points(l)
                for k in SEASON_STATS:
                    a[k] += l[k]
                if l['batted']:
                    a['inn'] += 1
                    a['no'] += not l['out']
                    a['hs'] = max(a['hs'], l['r'])
                    a['fifty'] += 50 <= l['r'] < 100
                    a['hund'] += l['r'] >= 100
    return players


def compact_match(m):
    keep = ('pid', 'team', 'bat_pos', 'r', 'bf', 'f4', 's6', 'out', 'how', 'lb', 'rc', 'wk', 'dots',
            'mdn', 'wd', 'nb', 'ct', 'st', 'ro', 'ro_solo', 'batted', 'bowled')
    return {**{k: m[k] for k in ('id', 'date', 'venue', 'city', 'teams', 'result', 'final')},
            'lines': [{k: l[k] for k in keep} | {'sc': sc_points(l)} | ({'sub': True} if l.get('sub') else {})
                      for l in m['lines'] if l['pid']]}


def main():
    by_season = cricsheet.parse_all(cricsheet.load_zip())
    idmap_path = DATA / 'idmap.json'
    previous = json.loads(idmap_path.read_text()) if idmap_path.exists() else {}
    idmap, ca_names = register.ca_idmap(by_season, previous)
    players = aggregate(by_season, register.full_names(by_season) | ca_names)

    baseline = guards.load_baseline()
    guards.fail_if(guards.check_history(by_season, players, baseline), 'cricsheet')

    fx = fixture.build()
    guards.fail_if(fixture.check(fx), 'fixture')

    sq, new_players = squads.build(players)
    avail = json.loads((CURATED / 'availability.json').read_text(encoding='utf-8'))
    notes = json.loads((CURATED / 'notes.json').read_text(encoding='utf-8'))
    unknown = squads.link(avail['links'], sq) + squads.link(notes, sq)
    guards.fail_if([f'curated entry names {u}, who is not in that squad' for u in unknown], 'curated')
    team_of = {r['pid']: team for team, rs in sq['teams'].items() for r in rs}
    for team, rs in sq['teams'].items():
        for r in rs:
            if r['pid'] in players:
                players[r['pid']]['n'] = r['n']

    for season, ms in by_season.items():
        write_json(DATA / 'matches' / f'{season_file(season)}.json', [compact_match(m) for m in ms])
    write_json(DATA / 'players.json', players)
    write_json(DATA / 'fixture.json', fx)
    write_json(DATA / 'squads.json', sq)
    write_json(DATA / 'availability.json', avail)
    write_json(DATA / 'notes.json', sorted(notes, key=lambda n: n['date'], reverse=True))
    write_json(DATA / 'rounds.json', json.loads((CURATED / 'rounds.json').read_text()))
    write_json(DATA / 'roles.json', roles.shifts(by_season, team_of, sq['as_of']))
    write_json(idmap_path, dict(sorted(idmap.items())))
    write_json(guards.BASELINE, guards.ratchet(by_season, players, baseline))
    write_json(DATA / 'meta.json', {
        'built': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'seasons': sorted(by_season),
        'matches': sum(len(v) for v in by_season.values()),
        'players': len(players),
        'ca_linked_players': len(idmap),
    })
    print(f'{len(players)} players, {sum(len(v) for v in by_season.values())} matches, '
          f'{len(fx)} fixtures, {len(idmap)} CA ids linked')
    print(f'{len(new_players)} squad players with no BBL history: {", ".join(new_players)}')


if __name__ == '__main__':
    main()
