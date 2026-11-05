"""Squad players' records outside the BBL: internationals, Australian domestic and franchise T20."""
import io
import json
import time
import zipfile
from datetime import date

from .common import CACHE, CURATED, fetch
from .cricsheet import iter_matches, parse_match
from .register import norm
from .scoring import sc_points
from .squads import _key

URL = 'https://cricsheet.org/downloads/{}_male_json.zip'
DIR = CACHE / 'elsewhere'
# Between 6 and 7 days, so a cache restored on the first run of an ISO week is always refetched
# and the rest of that week's daily runs reuse it.
MAX_AGE_H = 156
STATS = ('r', 'bf', 'f4', 's6', 'lb', 'rc', 'wk', 'ct', 'st', 'ro')
FORM = 10
ACTIVE_YEARS = 3
MIN_LINKED = 0.95


def comps():
    return json.loads((CURATED / 'competitions.json').read_text(encoding='utf-8'))['comps']


def load(code, max_age_h=MAX_AGE_H):
    path = DIR / f'{code}_male_json.zip'
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_h * 3600:
        DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(URL.format(code)))
    return zipfile.ZipFile(io.BytesIO(path.read_bytes()))


def _agg():
    return {'m': 0, 'inn': 0, 'no': 0, 'hs': 0, 'hsn': False, 'f50': 0, 'h100': 0, 'w5': 0, 'bb': None,
            **{k: 0 for k in STATS}}


def add(a, l, sc=None):
    a['m'] += 1
    for k in STATS:
        a[k] += l[k]
    for r, _, out in l['bi']:
        a['inn'] += 1
        a['no'] += not out
        if r > a['hs'] or (r == a['hs'] and not out):
            a['hs'], a['hsn'] = r, not out
        a['f50'] += 50 <= r < 100
        a['h100'] += r >= 100
    for _, rc, wk in l['wi']:
        a['w5'] += wk >= 5
        if a['bb'] is None or (wk, -rc) > (a['bb'][0], -a['bb'][1]):
            a['bb'] = [wk, rc]
    if sc is not None:
        a['sc'] = a.get('sc', 0) + sc
        a['scm'] = a.get('scm', 0) + 1


def _init_key(name):
    """Cricsheet's 'JM Bairstow' style -> ('j', 'bairstow'); None for full first names."""
    first = name.split()[0]
    return (first[0].lower(), norm(name)[-1]) if first.isupper() and len(first) <= 4 else None


def _curated_init(name):
    toks = norm(name)
    return toks[0][0], toks[-1]


def collect(known, newcomers, since, cc=None):
    """Aggregate every competition for known pids plus anyone whose name could be a newcomer."""
    want_key = {_key(r['n']) for r in newcomers}
    want_init = {_curated_init(r['n']) for r in newcomers}
    found, counts = {}, {}
    for c in cc or comps():
        n = 0
        for mid, d in iter_matches(load(c['code'])):
            meta, lines = parse_match(mid, d, code=lambda t: t)
            n += 1
            for l in lines:
                pid = l['pid']
                if l.get('sub') or not pid:
                    continue
                if pid not in known and pid not in found and _key(l['name']) not in want_key \
                        and _init_key(l['name']) not in want_init:
                    continue
                p = found.setdefault(pid, {'n': l['name'], 'last': '', 'c': {}, 'y': {}, 'f': []})
                if meta['date'] >= p['last']:
                    p['last'], p['n'] = meta['date'], l['name']
                sc = sc_points(l) if c.get('sc') else None
                add(p['c'].setdefault(c['code'], {}).setdefault(meta['season'], _agg()), l, sc)
                if meta['date'] >= since:
                    add(p['y'].setdefault(c['g'], _agg()), l, sc)
                p['f'].append({'d': meta['date'], 'c': c['code'], 'o': l['opp'], 'b': l['bi'], 'w': l['wi']}
                              | ({'sc': sc} if sc is not None else {}))
        counts[c['code']] = n
    return found, counts


def resolve(newcomers, found, known, active):
    """Give newcomers their Cricsheet id when exactly one same-named player has played since `active`."""
    unresolved = []
    for r in newcomers:
        pool = [pid for pid, p in found.items() if pid not in known and p['last'] >= active]
        cand = [pid for pid in pool if _key(found[pid]['n']) == _key(r['n'])] or \
               [pid for pid in pool if _init_key(found[pid]['n']) == _curated_init(r['n'])]
        if len(cand) == 1:
            r['pid'], r['cs'] = cand[0], found[cand[0]]['n']
        else:
            unresolved.append(r['n'] + (f' (ambiguous: {[found[c]["n"] for c in cand]})' if cand else ''))
    return unresolved


def check(counts, found, known, baseline):
    problems = [f'{code}: {counts.get(code, 0)} matches, baseline {n}'
                for code, n in baseline.get('comp_matches', {}).items() if counts.get(code, 0) < n]
    linked = sum(pid in found for pid in known)
    if known and linked < MIN_LINKED * len(known):
        problems.append(f'only {linked} of {len(known)} squad players have a record outside the BBL')
    return problems


def build(sq, baseline, today=None):
    today = today or date.today()
    since = date(today.year - 1, today.month, 1).isoformat()
    active = date(today.year - ACTIVE_YEARS, today.month, 1).isoformat()
    rows = [r for rs in sq['teams'].values() for r in rs]
    known = {r['pid'] for r in rows if not r.get('new')}
    newcomers = [r for r in rows if r.get('new')]
    cc = comps()
    found, counts = collect(known, newcomers, since, cc)
    problems = check(counts, found, known, baseline)
    unresolved = resolve(newcomers, found, known, active)
    players = {}
    for r in rows:
        p = found.get(r['pid'])
        if p:
            players[r['pid']] = {'n': p['n'], 'c': p['c'], 'y': p['y'],
                                 'f': sorted(p['f'], key=lambda g: g['d'])[-FORM:]}
    out = {'since': since, 'comps': {c['code']: {k: v for k, v in c.items() if k != 'code'} for c in cc},
           'players': players}
    return out, counts, unresolved, problems
