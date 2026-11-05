import csv
import io
import json
import re
import time
import unicodedata
from collections import defaultdict

from .common import CACHE, ca, fetch, team_code

NAMES_URL = 'https://cricsheet.org/register/names.csv'
CA_HISTORY = {'2024/25': 2673, '2025/26': 3185}


def _cached(name, url, max_age_h=24):
    path = CACHE / name
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_h * 3600:
        CACHE.mkdir(exist_ok=True)
        path.write_bytes(fetch(url))
    return path.read_text(encoding='utf-8')


def _is_initials(token):
    return token.isupper() and len(token) <= 4


def full_names(by_season):
    """Cricsheet id -> best full-name variant ("A Agar" -> "Ashton Agar")."""
    variants = defaultdict(list)
    for row in csv.DictReader(io.StringIO(_cached('names.csv', NAMES_URL))):
        variants[row['identifier']].append(row['name'])
    out = {}
    for ms in by_season.values():
        for m in ms:
            for l in m['lines']:
                pid, name = l['pid'], l['name']
                if pid in out:
                    continue
                surname = name.split()[-1]
                good = [v for v in variants.get(pid, [])
                        if not _is_initials(v.split()[0]) and v.split()[-1] == surname]
                out[pid] = max(good, key=len) if good else name
    return out


def norm(name):
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z ]', '', s).split()


def _scorecard(fid):
    path = CACHE / 'ca' / f'{fid}.json'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ca('views/scorecard', fixtureId=fid)), encoding='utf-8')
    return json.loads(path.read_text(encoding='utf-8'))


def align(ca_players, cs_lines):
    """Pair CA players with Cricsheet lines of the same team by surname, then first initial."""
    pairs = {}
    for team in {l['team'] for l in cs_lines if l['team']}:
        cs = [l for l in cs_lines if l['team'] == team]
        for p in ca_players.get(team, []):
            toks = norm(p['displayName'])
            cand = [l for l in cs if norm(l['name'])[-1] == toks[-1]]
            if len(cand) > 1:
                cand = [l for l in cand if norm(l['name'])[0][0] == toks[0][0]]
            if len(cand) == 1:
                pairs[str(p['id'])] = cand[0]['pid']
    return pairs


def ca_idmap(by_season, previous=None):
    """(CA player id -> Cricsheet id, Cricsheet id -> CA display name). The id map only ever grows."""
    idmap = dict(previous or {})
    display = {}
    for season, comp in CA_HISTORY.items():
        cs_by_key = {(m['date'], frozenset(m['teams'])): m for m in by_season.get(season, [])}
        for f in ca('fixtures/yearfilter', competitionId=comp, limit=60, isInningInclude='true')['fixtures']:
            if not f['isCompleted']:
                continue
            m = cs_by_key.get((f['startDateTime'][:10], frozenset(
                [f['homeTeam']['shortName'], f['awayTeam']['shortName']])))
            if not m:
                continue
            sc = _scorecard(f['id'])
            ids = {f['homeTeam']['id']: team_code(f['homeTeam']['name']),
                   f['awayTeam']['id']: team_code(f['awayTeam']['name'])}
            by_team = defaultdict(list)
            for p in sc.get('players') or []:
                by_team[ids[p['teamId']]].append(p)
                display[str(p['id'])] = p['displayName']
            idmap.update(align(by_team, m['lines']))
    return idmap, {pid: display[cid] for cid, pid in idmap.items() if cid in display}
