import pytest

from pipeline.cricsheet import _blank
from pipeline.scoring import sc_points


def line(**kw):
    return _blank() | kw


# Worked examples published at fantasyleaguelens.com/supercoach-bbl-scoring.
@pytest.mark.parametrize('kw, expected', [
    (dict(r=45, bf=30), 65),
    (dict(r=45, bf=40), 45),
    (dict(r=18, bf=8), 18),
    (dict(lb=24, wk=2, rc=24, dots=11, wd=1), 65),
    (dict(lb=24, wk=3, rc=32, dots=9), 84),
    (dict(lb=24, rc=14, dots=13, mdn=1), 53),
])
def test_published_examples(kw, expected):
    assert sc_points(line(**kw)) == expected


def test_band_edges():
    assert sc_points(line(r=32, bf=20)) == 32 + 25           # SR exactly 160
    assert sc_points(line(r=20, bf=17)) == 20                # SR 117.6, below every band
    assert sc_points(line(lb=18, rc=12)) == 25               # ER exactly 4, exactly 3 overs
    assert sc_points(line(lb=17, rc=0, dots=17)) == 17       # under 3 overs: no ER bonus
    assert sc_points(line(lb=24, rc=33)) == 0                # ER 8.25


def test_hundred_bonus_replaces_fifty_and_hauls_stack():
    assert sc_points(line(r=100, bf=50)) == 100 + 25 + 20
    assert sc_points(line(lb=24, rc=40, wk=6)) == 120 + 20


def test_fielding_and_shared_run_out():
    assert sc_points(line(ct=2, st=1, ro=2, ro_solo=1)) == 20 + 15 + 20 + 10
