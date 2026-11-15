"""How each BBL|16 ground has played: first-innings scores against the league, and whether this season differs."""
import json
import statistics as st
from collections import defaultdict

from .common import CURATED
from .scoring import sc_points

WINDOW = 5
MIN_HIST = 5
# A lean needs both size and evidence: venue means are noisy (about 29 runs SD per innings).
LEAN_RUNS, CHANGE_RUNS, SIGMA = 8, 10, 2
# Until this many full first innings exist this season, compare against the window's average instead.
EARLY = 10
# Spin against pace, in bowling SC points per over. A match counts when each kind bowled at least 3 overs.
SPIN_MIN_BALLS, SPIN_LEAN = 18, 1.5


def season_of(iso):
    y = int(iso[:4]) - (iso[5:7] < '07')
    return f'{y}/{(y + 1) % 100:02d}'


def first_innings(m):
    """First-innings total, only if it ran its full 20 overs or was bowled out (no rain cuts)."""
    i = m['inns'][0] if m.get('inns') else None
    return i['runs'] if i and (i['balls'] >= 120 or i['wk'] == 10) else None


def _lean(diff, n, sd):
    if n < MIN_HIST:
        return None
    if abs(diff) >= LEAN_RUNS and abs(diff) >= SIGMA * sd / n ** .5:
        return 'batting' if diff > 0 else 'bowling'
    return 'even'


def bowling_points(l):
    return sc_points({**l, 'r': 0, 'bf': 0, 'ct': 0, 'st': 0, 'ro': 0, 'ro_solo': 0})


def spin_pace(m, kinds):
    """{'spin': [balls, points], 'pace': [...]} for one match, or None if either kind bowled too little."""
    a = {'spin': [0, 0], 'pace': [0, 0]}
    for l in m['lines']:
        if l['lb'] and (k := kinds.get(l['pid'])):
            a[k][0] += l['lb']
            a[k][1] += bowling_points(l)
    return a if min(a['spin'][0], a['pace'][0]) >= SPIN_MIN_BALLS else None


def spin_build(by_season, past, alias, kinds):
    """Per venue: how much better spinners scored than pacers there, against the league in the same seasons."""
    rows = defaultdict(list)  # venue -> (match totals, spin-minus-pace points per over minus that season's league)
    league = {'spin': [0, 0], 'pace': [0, 0]}
    for s in past:
        xs = [(alias.get(m['venue']), a) for m in by_season[s] if (a := spin_pace(m, kinds))]
        if not xs:
            continue
        gap = lambda a: 6 * a['spin'][1] / a['spin'][0] - 6 * a['pace'][1] / a['pace'][0]
        mu = st.mean(gap(a) for _, a in xs)
        for v, a in xs:
            for k in league:
                league[k] = [x + y for x, y in zip(league[k], a[k])]
            if v:
                rows[v].append((a, gap(a) - mu))
    ds = [d for v in rows.values() for _, d in v]
    sd = st.pstdev(ds) if len(ds) > 1 else 0
    ppo = lambda t: round(6 * t[1] / t[0], 1) if t[0] else None
    out = {}
    for v, xs in rows.items():
        tot = {k: [sum(a[k][i] for a, _ in xs) for i in (0, 1)] for k in ('spin', 'pace')}
        diff = st.mean(d for _, d in xs)
        n = len(xs)
        lean = None if n < MIN_HIST else (
            ('spin' if diff > 0 else 'pace') if abs(diff) >= SPIN_LEAN and abs(diff) >= SIGMA * sd / n ** .5 else 'even')
        out[v] = {'n': n, 'spin': ppo(tot['spin']), 'pace': ppo(tot['pace']), 'diff': round(diff, 1), 'lean': lean}
    return {'spin': ppo(league['spin']), 'pace': ppo(league['pace']), 'sd': round(sd, 1)}, out


def build(by_season, fx, cur=None, kinds=None):
    cur = cur if cur is not None else json.loads((CURATED / 'venues.json').read_text(encoding='utf-8'))
    current = season_of(min(m['start'] for m in fx))
    past = sorted(s for s in by_season if s < current)[-WINDOW:]
    alias = {name: vid for vid, v in cur.items() for name in v['cricsheet']}

    problems = [f'fixture venue {v["id"]} ({v["name"]}) has no entry in curated/venues.json'
                for v in {m['venue']['id']: m['venue'] for m in fx if m['venue']}.values() if str(v['id']) not in cur]
    problems += [f'{current} match {m["id"]} is at "{m["venue"]}", which no curated/venues.json entry lists'
                 for m in by_season.get(current, []) if m['venue'] not in alias]

    window_runs = [r for s in past for m in by_season[s] if (r := first_innings(m)) is not None]
    rows = defaultdict(list)  # venue -> (season, runs, runs minus the league average)
    for s in past + [current]:
        xs = [(alias.get(m['venue']), r) for m in by_season.get(s, []) if (r := first_innings(m)) is not None]
        if not xs:
            continue
        mu = st.mean(r for _, r in xs) if s != current or len(xs) >= EARLY else st.mean(window_runs)
        for v, r in xs:
            if v:
                rows[v].append((s, r, r - mu))
    ds = [d for v in rows.values() for s, _, d in v if s != current]
    sd = st.pstdev(ds) if len(ds) > 1 else 0

    spin_league, spin = spin_build(by_season, past, alias, kinds or {})
    out = {}
    for vid, meta in cur.items():
        hist = [x for x in rows.get(vid, []) if x[0] != current]
        now = [x for x in rows.get(vid, []) if x[0] == current]
        h = None
        if hist:
            diff = st.mean(d for *_, d in hist)
            h = {'n': len(hist), 'par': round(st.mean(r for _, r, _ in hist)), 'diff': round(diff, 1),
                 'lean': _lean(diff, len(hist), sd),
                 'seasons': [{'s': s, 'n': len(g), 'par': round(st.mean(g))}
                             for s in past if (g := [r for ss, r, _ in hist if ss == s])]}
        n = None
        if now:
            diff = st.mean(d for *_, d in now)
            n = {'n': len(now), 'par': round(st.mean(r for _, r, _ in now)), 'diff': round(diff, 1), 'changed': None}
            if h and h['lean'] is not None:
                delta = diff - h['diff']
                se = sd * (1 / len(now) + 1 / h['n']) ** .5
                if abs(delta) >= CHANGE_RUNS and abs(delta) >= SIGMA * se:
                    n['changed'] = 'higher' if delta > 0 else 'lower'
        out[vid] = {'hist': h, 'now': n, 'spin': spin.get(vid),
                    'notes': sorted(meta.get('notes', []), key=lambda x: x['date'], reverse=True)}
    return {'season': current, 'window': [past[0], past[-1]] if past else None,
            'avg': round(st.mean(window_runs)) if window_runs else None, 'sd': round(sd, 1),
            'spin': spin_league, 'venues': out}, problems
