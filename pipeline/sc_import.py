"""SuperCoach JSON saved by hand from a logged-in browser -> data/sc.json and, once complete, official rounds."""
import json
import re
from datetime import datetime, timedelta, timezone

from .common import CURATED
from .squads import _key

RAW = CURATED / 'sc_raw'
SC_TEAMS = {'ADL': 'STR', 'BNE': 'HEA', 'HOB': 'HUR', 'MLR': 'REN', 'MLS': 'STA', 'PER': 'SCO', 'SY6': 'SIX', 'SYT': 'THU'}
AEDT = timezone(timedelta(hours=11))


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _round_files(prefix):
    files = {}
    for p in RAW.glob(f'{prefix}*.json'):
        m = re.fullmatch(rf'{prefix}(?:-round(\d+))?\.json', p.name)
        if m:
            files[int(m.group(1) or 0)] = p
    return dict(sorted(files.items()))


def rules(settings):
    g, c = settings['game'], settings['competition']
    return {
        'cap': g['starting_salarycap'],
        'squad': g['max_players_for_team'],
        'active': g['max_active_players_for_team'],
        'positions': {p['id']: {'squad': p['max_players'], 'active': p['active_max_players']} for p in g['positions']},
        'trades_round': g['game_max_changes'],
        'trades_total': g['game_max_total_changes'],
        'boosts': g['max_boosts'],
        'emergencies': g['game_num_emergencies'],
        'rounds': g['final_scoring_round'],
        'finals_round': g['game_finals_round'],
        'lockout': c['lockout_start'],
    }


def match_players(sc_players, squads, name_map):
    """SC player -> squad pid by team and name. Returns (pid -> SC player, problems)."""
    index = {(team, _key(r['n'])): r['pid'] for team, rs in squads['teams'].items() for r in rs}
    out, problems = {}, []
    for p in sc_players:
        team = SC_TEAMS.get(p['team']['abbrev'])
        full = f"{p['first_name']} {p['last_name']}"
        pid = index.get((team, _key(name_map.get(full, full))))
        if not pid:
            problems.append(f'SC player {team} {full} is not in curated/squads.json '
                            '(add them, or map the SC name in curated/sc_names.json)')
        elif pid in out:
            problems.append(f'two SC players match {team} {full}')
        else:
            out[pid] = p
    return out, problems


def player_row(p):
    st = max(p['player_stats'], key=lambda s: s['round'])
    row = {
        'id': p['id'],
        'pos': [x['position'] for x in sorted(p['positions'], key=lambda x: x['sort'])],
        'price': st['price'],
        'own': round(st['owned'], 1) if st.get('owned') is not None else None,
    }
    if st['price_change']:
        row['chg'] = st['price_change']
    if st['total_games']:
        row['g'], row['pts'] = st['total_games'], st['total_points']
    if p['previous_games']:
        row['prev'] = [p['previous_games'], p['previous_total']]
    if p['injury_suspension_status']:
        row['inj'] = p['injury_suspension_status_text'] or p['injury_suspension_status']
    return row


def rounds_from(sc_matches, fixture):
    """SC fixture -> round date ranges. Every SC match must line up with a CA fixture by kickoff and teams."""
    by_start = {}
    for m in fixture:
        by_start.setdefault(m['start'], []).append(m)
    rounds, problems, seen = {}, [], set()
    for s in sc_matches:
        utc = datetime.fromisoformat(s['kickoff']).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        teams = {SC_TEAMS.get((s.get(k) or {}).get('abbrev')) for k in ('team1', 'team2')} - {None}
        cands = [m for m in by_start.get(utc, []) if not teams or teams <= {m['home'], m['away']}]
        if len(cands) != 1:
            problems.append(f"SC round {s['round']} match {s['kickoff']} {'/'.join(sorted(teams))} "
                            f'has {len(cands)} CA fixture matches')
            continue
        seen.add(cands[0]['id'])
        day = datetime.fromisoformat(s['kickoff']).astimezone(AEDT).date().isoformat()
        r = rounds.setdefault(s['round'], {'round': s['round'], 'start': day, 'end': day, 'stages': set()})
        r['start'], r['end'] = min(r['start'], day), max(r['end'], day)
        r['stages'].add(cands[0]['stage'])
    out = []
    for n in sorted(rounds):
        r = rounds[n]
        stages = r.pop('stages')
        out.append(r | ({'finals': True} if 'league' not in stages else {}))
        if 'league' in stages and len(stages) > 1:
            problems.append(f'SC round {n} mixes league and finals matches')
    for a, b in zip(out, out[1:]):
        if b['start'] <= a['end']:
            problems.append(f"SC rounds {a['round']} and {b['round']} overlap ({a['end']} / {b['start']})")
    complete = not problems and seen == {m['id'] for m in fixture}
    return out, complete, problems


def build(squads, fixture):
    """Returns (sc.json payload or None, official rounds or None, problems, notes for the build log)."""
    players_files = _round_files('players')
    if not (RAW / 'settings.json').exists() or not players_files:
        return None, None, [], ['no SuperCoach snapshot saved yet']
    settings = _load(RAW / 'settings.json')
    sc_players = _load(list(players_files.values())[-1])
    names_path = CURATED / 'sc_names.json'
    name_map = _load(names_path) if names_path.exists() else {}
    matched, problems = match_players(sc_players, squads, name_map)
    in_sc = set(matched)
    notes = [f"in our squads but not in SuperCoach: {team} {r['n']}"
             for team, rs in squads['teams'].items() for r in rs if r['pid'] not in in_sc]

    sc_matches = [m for p in _round_files('fixture').values() for m in _load(p)]
    by_id = {m['id']: m for m in sc_matches}
    rounds, complete, round_problems = rounds_from(list(by_id.values()), fixture)
    problems += round_problems
    if not complete:
        notes.append(f'SuperCoach fixture covers {len(by_id)} of {len(fixture)} matches, so the draft rounds stay')

    stats = [s for p in sc_players for s in p['player_stats']]
    updated = max(s['updated_at'] for s in stats)
    sc = {
        'round': max(s['round'] for s in stats),
        'updated': datetime.fromisoformat(updated).astimezone(timezone.utc).isoformat(timespec='seconds'),
        'rules': rules(settings),
        'players': {pid: player_row(p) for pid, p in sorted(matched.items())},
    }
    official = {'draft': False, 'source': 'SuperCoach real_fixture', 'rounds': rounds} if complete else None
    return sc, official, problems, notes
