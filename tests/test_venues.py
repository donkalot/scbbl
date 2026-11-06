from pipeline import venues

CUR = {'1': {'cricsheet': ['Flat Track', 'Flat Track (old name)'], 'notes': [{'date': '2026-11-01', 'text': 'Re-laid.'}]},
       '2': {'cricsheet': ['Average Ground'], 'notes': []},
       '3': {'cricsheet': [], 'notes': []}}
FX = [{'start': '2026-12-12T09:10:00Z', 'venue': {'id': 1, 'name': 'Flat Track'}},
      {'start': '2026-12-13T09:10:00Z', 'venue': {'id': 3, 'name': 'New Ground'}},
      {'start': '2027-01-20T09:10:00Z', 'venue': None}]


def m(venue, runs, balls=120, wk=5):
    return {'id': f'{venue}-{runs}', 'venue': venue, 'inns': [{'team': 'X', 'runs': runs, 'balls': balls, 'wk': wk}]}


def seasons(n=5, flat=(190, 186, 194), avg=(160, 150, 170, 155, 165)):
    out = {}
    for i in range(n):
        y = 2021 + i
        out[f'{y}/{(y + 1) % 100:02d}'] = ([m('Flat Track (old name)' if i == 0 else 'Flat Track', r) for r in flat]
                                           + [m('Average Ground', r) for r in avg])
    return out


def test_season_of_splits_in_july():
    assert venues.season_of('2026-12-12T09:10:00Z') == '2026/27'
    assert venues.season_of('2027-01-20T09:10:00Z') == '2026/27'
    assert venues.season_of('2026-07-01') == '2026/27'


def test_rain_cut_first_innings_are_left_out_but_all_outs_count():
    assert venues.first_innings(m('X', 150, balls=120)) == 150
    assert venues.first_innings(m('X', 98, balls=87, wk=10)) == 98
    assert venues.first_innings(m('X', 120, balls=90, wk=4)) is None
    assert venues.first_innings({'inns': []}) is None


def test_lean_needs_size_and_evidence_and_aliases_count():
    out, problems = venues.build(seasons(), FX, CUR)
    assert problems == []
    v = out['venues']
    assert out['season'] == '2026/27' and out['window'] == ['2021/22', '2025/26']
    assert v['1']['hist']['n'] == 15 and v['1']['hist']['lean'] == 'batting'
    assert v['2']['hist']['lean'] == 'bowling'
    assert [s['s'] for s in v['1']['hist']['seasons']] == ['2021/22', '2022/23', '2023/24', '2024/25', '2025/26']
    assert v['3'] == {'hist': None, 'now': None, 'notes': []}
    assert v['1']['notes'][0]['text'] == 'Re-laid.'
    # Same tilt but too few games to call.
    few, _ = venues.build(seasons(n=1), FX, CUR)
    assert few['venues']['1']['hist']['lean'] is None


def test_noisy_ground_is_even():
    bs = seasons(flat=(230, 120, 200), avg=(160, 150, 170, 155, 165))
    out, _ = venues.build(bs, FX, CUR)
    assert out['venues']['1']['hist']['lean'] == 'even'


def test_this_season_flags_a_clear_change_only():
    bs = seasons()
    bs['2026/27'] = [m('Flat Track', r) for r in (150, 145, 155, 148)] + [m('Average Ground', 160)]
    out, _ = venues.build(bs, FX, CUR)
    now = out['venues']['1']['now']
    assert now['n'] == 4 and now['par'] == 150 and now['changed'] == 'lower'
    # Early in the season it's compared with the window's average, not the handful of games so far.
    window_avg = (5 * (190 + 186 + 194) + 5 * (160 + 150 + 170 + 155 + 165)) / 40
    assert now['diff'] == round((150 + 145 + 155 + 148) / 4 - window_avg, 1)
    bs['2026/27'] = [m('Flat Track', 188)]
    out, _ = venues.build(bs, FX, CUR)
    assert out['venues']['1']['now']['changed'] is None


def test_unmapped_grounds_fail_the_build():
    bs = seasons()
    bs['2026/27'] = [m('Renamed Stadium', 170)]
    _, problems = venues.build(bs, FX + [{'start': '2026-12-20T09:10:00Z', 'venue': {'id': 9, 'name': 'Nowhere'}}], CUR)
    assert any('Renamed Stadium' in p for p in problems)
    assert any('fixture venue 9' in p for p in problems)
