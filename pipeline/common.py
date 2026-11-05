import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
CURATED = ROOT / 'curated'
CACHE = ROOT / '.cache'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
CA_API = 'https://apiv2.cricket.com.au/web'

# Cricsheet full names and cricket.com.au names ("Brisbane Heat Men") both map to CA shortNames.
TEAMS = {
    'Adelaide Strikers': 'STR',
    'Brisbane Heat': 'HEA',
    'Hobart Hurricanes': 'HUR',
    'Melbourne Renegades': 'REN',
    'Melbourne Stars': 'STA',
    'Perth Scorchers': 'SCO',
    'Sydney Sixers': 'SIX',
    'Sydney Thunder': 'THU',
}


def team_code(name):
    base = name.removesuffix(' Men').strip()
    return TEAMS[base]


def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def ca(path, **params):
    q = '&'.join(f'{k}={v}' for k, v in params.items())
    sep = '&' if q else ''
    return json.loads(fetch(f'{CA_API}/{path}?{q}{sep}jsconfig=eccn%3Atrue&format=json'))


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
