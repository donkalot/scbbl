from collections import defaultdict
from statistics import mean

RECENT = 3
MIN_PRIOR = 4
PRIOR_SEASONS = 3
POS_SHIFT = 2
BOWL_ON, BOWL_OFF = 2.0, 0.5


def _history(by_season):
    hist = defaultdict(list)
    for season in sorted(by_season):
        for m in by_season[season]:
            for l in m['lines']:
                if l['pid'] and not l.get('sub'):
                    hist[l['pid']].append((m['date'], season, l))
    return hist


def _positions(xs):
    return [l['bat_pos'] for _, _, l in xs if l['batted'] and l['bat_pos']]


def _overs(xs):
    return mean(l['lb'] / 6 for _, _, l in xs)


def shifts(by_season, squad_team, squad_date):
    """Role changes for squad players: last 3 matches against earlier matches in the last 3 seasons."""
    seasons = sorted(by_season)
    window = set(seasons[-PRIOR_SEASONS:])
    out = []
    for pid, h in _history(by_season).items():
        team = squad_team.get(pid)
        if not team:
            continue
        recent = h[-RECENT:]
        prior = [x for x in h[:-RECENT] if x[1] in window]
        last_date, last_season, last = h[-1]
        base = {'pid': pid, 'date': last_date}
        if team != last['team']:
            stale = '' if last_season in window else f' (last played BBL in {last_season})'
            out.append(base | {'date': squad_date, 'kind': 'transfer',
                               'text': f"{last['team']} → {team} for BBL|16{stale}",
                               'from': last['team'], 'to': team})
        if len(recent) < RECENT or len(prior) < MIN_PRIOR or last_season not in window:
            continue
        rp, pp = _positions(recent), _positions(prior)
        if len(rp) >= 2 and len(pp) >= 3:
            a, b = mean(pp), mean(rp)
            if abs(b - a) >= POS_SHIFT:
                out.append(base | {'kind': 'bat_up' if b < a else 'bat_down',
                                   'text': f'Batting {"higher" if b < a else "lower"}: average position '
                                           f'{a:.1f} → {b:.1f} over the last {RECENT} games',
                                   'prior': round(a, 1), 'recent': round(b, 1)})
            if all(p <= 2 for p in rp) and sum(p <= 2 for p in pp) / len(pp) < 0.5:
                out.append(base | {'kind': 'opener', 'text': f'Opening in each of the last {len(rp)} innings '
                                   f'(opened {sum(p <= 2 for p in pp)} of {len(pp)} before)'})
        a, b = _overs(prior), _overs(recent)
        if b >= BOWL_ON and a < BOWL_OFF:
            out.append(base | {'kind': 'bowl_on', 'text': f'Started bowling: {a:.1f} → {b:.1f} overs a game',
                               'prior': round(a, 1), 'recent': round(b, 1)})
        elif b < BOWL_OFF and a >= BOWL_ON:
            out.append(base | {'kind': 'bowl_off', 'text': f'Stopped bowling: {a:.1f} → {b:.1f} overs a game',
                               'prior': round(a, 1), 'recent': round(b, 1)})
    out.sort(key=lambda s: (s['date'], s['pid']), reverse=True)
    return out
