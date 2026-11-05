"""How often it has rained in each fixture's match window, for matches beyond the 16-day forecast."""
import json
from datetime import datetime, timedelta

from .common import CACHE, fetch

ARCHIVE = ('https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}'
           '&start_date={a}&end_date={b}&hourly=precipitation&timezone=GMT')
DIR = CACHE / 'climate'
YEARS = 10
# Days either side of the match date, so each match has 70 samples rather than 10.
SPREAD = 3
WET_MM, HEAVY_MM = 1, 5


def _dt(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)


def _samples(m):
    start, end = _dt(m['start']), _dt(m['end'])
    for y in range(1, YEARS + 1):
        for off in range(-SPREAD, SPREAD + 1):
            shift = timedelta(days=off)
            # Feb 29 never occurs in a BBL window, so replace(year=) is safe.
            yield start.replace(year=start.year - y) + shift, end.replace(year=end.year - y) + shift


def _hours(s, e):
    """Open-Meteo labels each hour by its end, so label h covers (h-1, h]."""
    h = s.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while h - timedelta(hours=1) < e:
        yield h.strftime('%Y-%m-%dT%H:%M')
        h += timedelta(hours=1)


def hourly(lat, lon, a, b):
    path = DIR / f'{lat:.4f}_{lon:.4f}_{a}_{b}.json'
    if not path.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(ARCHIVE.format(lat=lat, lon=lon, a=a, b=b)))
    h = json.loads(path.read_text())['hourly']
    return dict(zip(h['time'], h['precipitation']))


def rates(m, rain):
    n = wet = heavy = 0
    for s, e in _samples(m):
        mm = [rain.get(h) for h in _hours(s, e)]
        if not mm or None in mm:
            continue
        total = sum(mm)
        n += 1
        wet += total >= WET_MM
        heavy += total >= HEAVY_MM
    return {'n': n, 'wet': wet, 'heavy': heavy}


def _key(m):
    return f"{m['venue']['lat']:.4f},{m['venue']['lon']:.4f}|{m['start']}|{m['end']}"


def build(fx, previous=None):
    """fixture id -> rain counts. Entries whose venue and times haven't changed are reused unfetched."""
    previous = previous or {}
    out, todo = {}, {}
    for m in fx:
        if not m.get('venue'):
            continue
        old = previous.get(str(m['id']))
        if old and old['k'] == _key(m):
            out[str(m['id'])] = old
        else:
            todo.setdefault((m['venue']['lat'], m['venue']['lon']), []).append(m)
    for (lat, lon), ms in todo.items():
        spans = [w for m in ms for w in _samples(m)]
        a = min(s for s, _ in spans).date().isoformat()
        b = max(e for _, e in spans).date().isoformat()
        rain = hourly(lat, lon, a, b)
        for m in ms:
            out[str(m['id'])] = {'k': _key(m), **rates(m, rain)}
    return dict(sorted(out.items()))
