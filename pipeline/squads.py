import json
from datetime import date

from .common import CURATED
from .register import norm

ALIASES = {'mitch': 'mitchell', 'matt': 'matthew', 'ollie': 'oliver', 'oli': 'oliver', 'tom': 'thomas',
           'nic': 'nicholas', 'nick': 'nicholas', 'jake': 'jacob', 'josh': 'joshua', 'sam': 'samuel', 'will': 'william'}


def _key(name):
    toks = norm(name)
    return (ALIASES.get(toks[0], toks[0]), toks[-1])


def resolve(curated, players):
    """Squad names -> player ids. Same-name players are split by who last played for the squad's team."""
    by_key, by_initial = {}, {}
    for pid, p in players.items():
        by_key.setdefault(_key(p['n']), []).append(pid)
        first = p['n'].split()[0]
        if first.isupper() and len(first) <= 4:
            by_initial.setdefault((first[0].lower(), norm(p['n'])[-1]), []).append(pid)

    def last_team(pid):
        s = players[pid]['s']
        return s[max(s)]['t']

    out, unresolved = {}, []
    for team, names in curated['teams'].items():
        rows = []
        for name in names:
            toks = norm(name)
            cand = by_key.get(_key(name)) or by_initial.get((toks[0][0], toks[-1]), [])
            if len(cand) > 1:
                cand = [c for c in cand if last_team(c) == team] or cand
            pid = cand[0] if len(cand) == 1 else None
            if pid is None:
                unresolved.append(f'{team} {name}' + (f' (ambiguous: {cand})' if cand else ''))
            row = {'pid': pid or 'new-' + '-'.join(norm(name)), 'n': name} | ({} if pid else {'new': True})
            if name in curated.get('overseas', {}):
                row['os'] = curated['overseas'][name]
            if curated.get('captains', {}).get(team) == name:
                row['c'] = True
            rows.append(row)
        out[team] = rows
    return {'as_of': curated['as_of'], 'source': curated['source'], 'teams': out}, unresolved


def build(players):
    return resolve(json.loads((CURATED / 'squads.json').read_text(encoding='utf-8')), players)


def link(rows, squads):
    """Attach the squad pid to curated rows that name a player by team + name; return names not found."""
    index = {(team, r['n']): r['pid'] for team, rs in squads['teams'].items() for r in rs}
    missing = []
    for row in rows:
        if row.get('player'):
            row['pid'] = index.get((row['team'], row['player']))
            if not row['pid']:
                missing.append(f"{row['team']} {row['player']}")
    return missing


def _iso(v):
    try:
        return date.fromisoformat(v).isoformat() == v
    except (TypeError, ValueError):
        return False


def check_availability(avail):
    """Dates are compared as strings, so they must be exact ISO dates; a link to a missing event would do nothing."""
    problems, events, bad = [], {}, set()
    for e in avail['events']:
        if e['id'] in events:
            problems.append(f"event {e['id']!r} is listed twice")
        events[e['id']] = e
        if not (_iso(e.get('start')) and _iso(e.get('end')) and e['start'] <= e['end']):
            problems.append(f"event {e['id']!r} dates {e.get('start')!r}..{e.get('end')!r} are not an ISO date range")
            bad.add(e['id'])
    for link in avail['links']:
        who, e = f"{link.get('team')} {link.get('player')}", events.get(link.get('event'))
        if not e:
            problems.append(f"{who} links to unknown event {link.get('event')!r}")
            continue
        if e['id'] in bad:
            continue
        start, end = link.get('from', e['start']), link.get('until', e['end'])
        if not (_iso(start) and _iso(end) and e['start'] <= start <= end <= e['end']):
            problems.append(f"{who} on {e['id']}: from/until {start!r}..{end!r} must be ISO dates within {e['start']}..{e['end']}")
    return problems
