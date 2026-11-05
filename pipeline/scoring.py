import json
from functools import cache

from .common import CURATED


@cache
def rules():
    return json.loads((CURATED / 'scoring.json').read_text())


def _band(value, bands, higher_is_better):
    for edge, pts in bands:
        if (value >= edge) if higher_is_better else (value <= edge):
            return pts
    return 0


def sc_points(l, table=None):
    """SuperCoach BBL points for one player-match line."""
    t = table or rules()
    bat, bwl, fld = t['batting'], t['bowling'], t['fielding']
    pts = l['r'] * bat['run']
    if l['r'] >= bat['sr_min_runs'] and l['bf']:
        pts += _band(round(100 * l['r'] / l['bf'], 2), bat['sr_bands'], True)
    pts += next((p for runs, p in bat['milestones'] if l['r'] >= runs), 0)

    pts += l['wk'] * bwl['wicket'] + l['wk'] // bwl['haul_every'] * bwl['haul_bonus']
    pts += l['mdn'] * bwl['maiden'] + l['dots'] * bwl['dot'] + (l['wd'] + l['nb']) * bwl['extra']
    if l['lb'] >= bwl['er_min_balls']:
        pts += _band(round(6 * l['rc'] / l['lb'], 2), bwl['er_bands'], False)

    # Cricsheet can't say which of two run-out fielders SuperCoach credits, so shared ones split.
    shared = l['ro'] - l['ro_solo']
    pts += l['ct'] * fld['catch'] + l['st'] * fld['stumping']
    pts += l['ro_solo'] * fld['run_out'] + shared * fld['run_out'] // 2
    return pts
