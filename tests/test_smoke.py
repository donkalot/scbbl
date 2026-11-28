"""End-to-end smoke test: serve the repo root and drive every tab in headless Chromium."""
import http.server
import json
import re
import pathlib
import socketserver
import threading

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8767
BASE = f'http://127.0.0.1:{PORT}/index.html'


@pytest.fixture(scope='module')
def server():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, *a):
            pass

    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Quiet)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield BASE
    httpd.shutdown()


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
    pg = ctx.new_page()
    pg.errors = []
    pg.on('pageerror', lambda e: pg.errors.append(str(e)))
    pg.on('console', lambda m: m.type == 'error' and pg.errors.append(m.text))
    yield pg
    assert pg.errors == [], pg.errors
    ctx.close()


def _squad_pid(team, name):
    sq = json.loads((ROOT / 'data' / 'squads.json').read_text(encoding='utf-8'))
    return next(r['pid'] for r in sq['teams'][team] if r['n'] == name)


@pytest.mark.parametrize('hash_, heading', [
    ('#/players', 'Players'),
    ('#/planner', 'Doubles and byes'),
    ('#/team', 'Team'),
    ('#/availability', 'Availability'),
    ('#/roles', 'Roles and news'),
])
def test_tab_renders(server, page, hash_, heading):
    page.goto(server + hash_)
    expect(page.locator('#app h2').first).to_have_text(heading)
    expect(page.locator('#tabs a.on')).to_have_count(1)


CSP_WATCH = "window.csp = []; document.addEventListener('securitypolicyviolation', e => window.csp.push(e.violatedDirective + ' ' + e.blockedURI));"


@pytest.mark.parametrize('hash_', ['#/players', '#/planner', '#/team', '#/availability', '#/roles', '#/matches'])
def test_every_tab_runs_under_the_content_security_policy(server, page, hash_):
    page.add_init_script(CSP_WATCH)
    page.goto(server + hash_)
    expect(page.locator('#app h2').first).to_be_visible()
    page.wait_for_timeout(300)
    assert page.evaluate('window.csp') == []
    assert 'Content-Security-Policy' in page.content()


def test_sources_are_labelled_with_their_host(server, page):
    page.goto(server + '#/roles')
    links = page.locator('#app a.muted[href^="https://"]')
    expect(links.first).to_be_visible()
    for href, text in links.evaluate_all('xs => xs.map(a => [a.href, a.textContent])'):
        assert text == re.sub(r'^www\.', '', href.split('/')[2]), href


@pytest.mark.parametrize('hash_', ['#/players?sort=constructor', '#/players?sort=__proto__', '#/team?sort=toString', '#/team?sort=hasOwnProperty'])
def test_odd_sort_params_fall_back_to_the_default(server, page, hash_):
    page.goto(server + hash_)
    expect(page.locator('#app h2').first).to_be_visible()


def test_players_search(server, page):
    page.goto(server + '#/players')
    rows = page.locator('#ptable tbody tr')
    expect(rows.first).to_be_visible()
    assert rows.count() >= 100
    page.fill('#q', 'marsh')
    expect(rows.filter(has_text='Mitchell Marsh')).to_have_count(1)
    assert rows.count() < 10


def test_planner_grid_has_every_team_with_ten_games(server, page):
    page.goto(server + '#/planner')
    rows = page.locator('#app table').first.locator('tbody tr')
    expect(rows).to_have_count(8)
    for i in range(8):
        expect(rows.nth(i).locator('td').last).to_have_text('10')


def test_player_page_loads_match_log(server, page):
    page.add_init_script(CSP_WATCH)
    page.goto(server + '#/player/' + _squad_pid('SCO', 'Mitchell Marsh'))
    expect(page.locator('#app h2').first).to_have_text('Mitchell Marsh')
    expect(page.locator('#log tbody tr').first).to_be_visible()
    expect(page.locator('#last5')).not_to_have_text('–')
    assert page.evaluate('window.csp') == []


@pytest.mark.parametrize('then, fails', [('player', False), ('list', False), ('list', True)], ids=['player', 'list', 'list-after-a-failed-fetch'])
def test_a_slow_match_log_never_lands_on_the_next_page(server, page, then, fails):
    pl = json.loads((ROOT / 'data' / 'players.json').read_text(encoding='utf-8'))
    old = next(pid for pid, p in pl.items() if sorted(p['s']) == ['2011/12', '2012/13'])
    held = []
    page.route('**/data/matches/2011-12.json', lambda r: held.append(r))
    page.route('**/data/matches/2012-13.json', lambda r: held.append(r))
    page.goto(server + '#/player/' + old)
    expect(page.locator('#log')).to_have_text('Loading matches…')
    if then == 'player':
        page.goto(server + '#/player/' + _squad_pid('SCO', 'Mitchell Marsh'))
        expect(page.locator('#log tbody tr').first).to_be_visible()
    else:
        page.goto(server + '#/players')
        expect(page.locator('#ptable tbody tr').first).to_be_visible()
    mine = "() => [document.querySelector('#app h2').textContent, ...['log', 'last5', 'venues'].map(id => document.getElementById(id)?.innerHTML)]"
    before = page.evaluate(mine)
    for r in held:
        r.fulfill(status=500, body='') if fails else r.continue_()
    page.wait_for_timeout(300)
    assert len(held) == 2 and page.evaluate(mine) == before
    expect(page.locator('#app')).not_to_contain_text('Something went wrong')
    assert all('status of 500' in e for e in page.errors) and (bool(page.errors) == fails)
    page.errors.clear()


def test_newcomer_page_shows_other_competitions(server, page):
    page.goto(server + '#/player/' + _squad_pid('REN', 'Jonny Bairstow'))
    expect(page.locator('#app h2').first).to_have_text('Jonny Bairstow')
    table = page.locator('#else table').first
    expect(table.locator('tbody tr', has_text='The Hundred')).to_have_count(1)
    expect(table.locator('tbody tr', has_text='IPL')).to_have_count(1)
    page.click('#else button:has-text("First-class")')
    expect(table.locator('tbody tr', has_text='Tests')).to_have_count(1)
    expect(table.locator('tbody tr', has_text='IPL')).to_have_count(0)
    expect(page.locator('#else table').nth(1).locator('tbody tr')).to_have_count(10)


def test_players_list_shows_t20_elsewhere(server, page):
    page.goto(server + '#/players')
    page.fill('#q', 'bairstow')
    cell = page.locator('#ptable tbody tr', has_text='Jonny Bairstow').locator('td').nth(9)
    expect(cell).to_contain_text('(')


def _round_cell(page, name):
    return page.locator('#ptable tbody tr', has_text=name).locator('td').nth(8)


def test_players_round_column_adds_up_a_double(server, page):
    # SCO play once in round 1 and twice in round 5; HUR have a bye in round 5.
    page.goto(server + '#/players?q=mitchell marsh&r=1')
    row = page.locator('#ptable tbody tr', has_text='Mitchell Marsh')
    proj = float(row.locator('td').nth(6).inner_text())
    expect(page.locator('#ptable thead')).to_contain_text('R1')
    one = _round_cell(page, 'Mitchell Marsh')
    expect(one).to_contain_text('×1')
    assert abs(float(one.inner_text().split()[0]) - proj) <= 1.5
    page.select_option('#rnd', '5')
    expect(page.locator('#ptable thead')).to_contain_text('R5')
    two = _round_cell(page, 'Mitchell Marsh')
    expect(two).to_contain_text('×2')
    expect(two).to_have_class(re.compile(r'\bg2\b'))
    assert abs(float(two.inner_text().split()[0]) - 2 * proj) <= 2.5
    assert 'r=5' in page.url
    hur = json.loads((ROOT / 'data' / 'squads.json').read_text(encoding='utf-8'))['teams']['HUR'][0]['n']
    page.fill('#q', hur)
    bye = _round_cell(page, hur)
    expect(bye).to_have_text('Bye')
    expect(bye).to_have_class(re.compile(r'\bg0\b'))


def test_players_sort_by_round_puts_doubles_first(server, page):
    # Round 5's only double is SCO, which the default order wouldn't put first.
    page.goto(server + '#/players?r=5&sort=round')
    rows = page.locator('#ptable tbody tr')
    expect(rows.first).to_be_visible()
    values = []
    for i in range(10):
        expect(rows.nth(i).locator('td').nth(2)).to_have_text('SCO')
        cell = rows.nth(i).locator('td').nth(8)
        expect(cell).to_contain_text('×2')
        values.append(float(cell.inner_text().split()[0]))
    assert values == sorted(values, reverse=True)


def test_players_round_column_skips_games_the_player_misses(server, page):
    page.goto(server + '#/players?r=1')
    cells = page.locator('#ptable tbody td.gx')
    expect(cells.first).to_be_visible()
    for row in page.locator('#ptable tbody tr', has=page.locator('td.gx')).all()[:5]:
        tds = row.locator('td')
        val, n = tds.nth(8).inner_text().split()
        available = int(n.lstrip('×').split('/')[0])
        assert abs(float(val) - available * float(tds.nth(6).inner_text())) <= 1.5 * max(available, 1)


def test_test_squad_players_miss_the_games_between_tests(server, page):
    # The Sixers' round 1 double falls on 15 Dec, between the first two Tests, and 17-19 Dec, during the second.
    page.goto(server + '#/players?q=steve smith&r=1')
    cell = _round_cell(page, 'Steve Smith')
    expect(cell).to_contain_text('×0/2')
    expect(cell).to_have_class(re.compile(r'\bgx\b'))
    rounds = json.loads((ROOT / 'data' / 'rounds.json').read_text(encoding='utf-8'))['rounds']
    after = next(r['round'] for r in rounds if r['start'] <= '2027-01-15' <= r['end'])
    page.select_option('#rnd', str(after))
    expect(_round_cell(page, 'Steve Smith')).not_to_have_class(re.compile(r'\bgx\b'))


def test_players_round_param_falls_back_and_the_default_stays_out_of_the_url(server, page):
    # Mid-season, so the default is the round in progress rather than round 1.
    page.clock.set_fixed_time('2027-01-03T12:00:00+11:00')
    page.goto(server + '#/players')
    expect(page.locator('#ptable tbody tr').first).to_be_visible()
    default = page.locator('#rnd').input_value()
    assert default == '5'
    page.goto(server + '#/players?r=99')
    expect(page.locator('#rnd')).to_have_value(default)
    other = '6'
    page.select_option('#rnd', other)
    assert f'r={other}' in page.url
    page.select_option('#rnd', default)
    assert 'r=' not in page.url


def test_players_show_supercoach_price_position_and_ownership(server, page):
    pid = _squad_pid('SCO', 'Mitchell Marsh')
    sc = json.loads((ROOT / 'data' / 'sc.json').read_text(encoding='utf-8'))['players'][pid]
    page.goto(server + '#/players?q=marsh')
    expect(page.locator('#app')).to_contain_text('SuperCoach prices and ownership for round')
    cells = page.locator('#ptable tbody tr', has_text='Mitchell Marsh').locator('td')
    expect(cells.nth(3)).to_have_text('/'.join(sc['pos']))
    expect(cells.nth(4)).to_have_text(f"${sc['price'] / 1000:.1f}k")
    # SC publishes no ownership pre-season, so the cell is blank until it does
    expect(cells.nth(5)).to_have_text(f"{sc['own']:.1f}" if sc.get('own') is not None else '')
    page.select_option('#pos', 'WKP')
    expect(page.locator('#ptable tbody tr', has_text='Mitchell Marsh')).to_have_count(0)
    page.goto(server + '#/player/' + pid)
    expect(page.locator('.stats')).to_contain_text("SC price")
    expect(page.locator('.stats')).to_contain_text(f"{sc['prev'][1]} pts in {sc['prev'][0]}")


def test_players_vs_price_sorts_and_shows_on_the_player_page(server, page):
    sc = json.loads((ROOT / 'data' / 'sc.json').read_text(encoding='utf-8'))['players']
    rate = int(re.search(r'perPoint: (\d+)', (ROOT / 'logic.js').read_text(encoding='utf-8')).group(1))
    page.goto(server + '#/players?sort=value')
    expect(page.locator('#ptable thead')).to_contain_text('vs price ▾')
    rows = page.locator('#ptable tbody tr')
    expect(rows.first).to_be_visible()
    vals = [float(rows.nth(i).locator('td').nth(7).inner_text().replace('−', '-')) for i in range(10)]
    assert vals == sorted(vals, reverse=True) and vals[0] >= 5
    expect(rows.first.locator('td').nth(7).locator('.pill.ok')).to_have_count(1)
    href = rows.first.locator('td.name a').get_attribute('href')
    pid = href.rsplit('/', 1)[1]
    assert abs(vals[0] - (float(rows.first.locator('td').nth(6).inner_text()) - sc[pid]['price'] / rate)) <= 0.11
    page.goto(server + href)
    expect(page.locator('#pricegap')).to_contain_text(f"Priced for {sc[pid]['price'] / rate:.1f} a game")
    expect(page.locator('#pricegap')).to_contain_text('underpriced')
    rookie = next(r for r in json.loads((ROOT / 'data' / 'squads.json').read_text(encoding='utf-8'))['teams']['SCO']
                  if r['pid'] in sc and not sc[r['pid']].get('prev'))
    page.goto(server + '#/players?q=' + rookie['n'])
    expect(page.locator('#ptable tbody tr', has_text=rookie['n']).locator('td').nth(7)).to_have_text('')
    page.goto(server + '#/player/' + rookie['pid'])
    expect(page.locator('.stats')).to_contain_text('SC price')
    expect(page.locator('#pricegap')).to_have_count(0)


def test_squad_add_shows_in_planner(server, page):
    page.goto(server + '#/players')
    page.fill('#q', 'marsh')
    row = page.locator('#ptable tbody tr', has_text='Mitchell Marsh')
    row.locator('button[data-squad]').click()
    expect(row.locator('button[data-squad]')).to_have_text('✓')
    page.goto(server + '#/planner')
    mine = page.locator('#app table').nth(1).locator('tbody tr', has_text='Mitchell Marsh')
    expect(mine).to_have_count(1)
    proj = float(mine.locator('td').nth(3).inner_text())
    r5 = mine.locator('td[data-r="5"]')
    expect(r5.locator('small')).to_be_visible()
    assert r5.inner_text().split()[0] == '2'
    assert abs(float(r5.locator('small').inner_text()) - 2 * proj) <= 2.5


def _sc_players():
    return json.loads((ROOT / 'data' / 'sc.json').read_text(encoding='utf-8'))['players']


def _seed(page, pids):
    page.add_init_script(f"localStorage.setItem('scbbl-squad', JSON.stringify({json.dumps(pids)}))")


def test_team_flags_a_squad_with_too_many_bowlers(server, page):
    sc = _sc_players()
    bowlers = [pid for pid, p in sc.items() if p['pos'] == ['BWL']][:9]
    _seed(page, bowlers)
    page.goto(server + '#/team')
    expect(page.locator('.stat').first).to_contain_text('9/17')
    cost = sum(sc[pid]['price'] for pid in bowlers)
    expect(page.locator('.stat').nth(1)).to_contain_text(f"${cost / 1000:.1f}k")
    expect(page.locator('#problems')).to_contain_text('No seat for')
    rows = page.locator('#team tbody tr')
    expect(rows).to_have_count(18)
    expect(rows.filter(has_text='Open')).to_have_count(9)


def test_team_fills_an_open_seat_within_budget(server, page):
    _seed(page, [])
    page.goto(server + '#/team')
    page.locator('#team tbody tr', has_text='WKP').first.locator('a', has_text='Pick').click()
    opts = page.locator('#opts tbody tr')
    expect(opts.first).to_be_visible()
    for i in range(opts.count()):
        assert 'WKP' in opts.nth(i).locator('td').nth(3).inner_text()
    pick = opts.first.locator('td.name a').inner_text()
    opts.first.locator('button[data-in]').click()
    expect(page.locator('#picker')).to_have_count(0)
    expect(page.locator('.stat').first).to_contain_text('1/17')
    expect(page.locator('#team tbody tr', has_text=pick).locator('td').first).to_have_text('WKP')


def test_team_trade_swaps_within_the_money_left(server, page):
    sc = _sc_players()
    marsh = _squad_pid('SCO', 'Mitchell Marsh')
    _seed(page, [marsh])
    page.goto(server + '#/team')
    page.locator('#team tbody tr', has_text='Mitchell Marsh').locator('a', has_text='Trade').click()
    expect(page.locator('#picker')).to_contain_text('Trade out Mitchell Marsh')
    page.click('#picker a:has-text("Cheapest")')
    opts = page.locator('#opts tbody tr')
    expect(opts.first.locator('td').nth(4)).to_have_text(f"${min(p['price'] for pid, p in sc.items() if pid != marsh) / 1000:.1f}k")
    pick = opts.first.locator('td.name a').inner_text()
    opts.first.locator('button[data-in]').click()
    expect(page.locator('#team tbody tr', has_text='Mitchell Marsh')).to_have_count(0)
    expect(page.locator('#team tbody tr', has_text=pick)).to_have_count(1)
    expect(page.locator('.stat').first).to_contain_text('1/17')


def _full_squad():
    sc = _sc_players()
    only = lambda *pos: [pid for pid, p in sc.items() if p['pos'] == list(pos)]
    return only('WKP', 'BAT')[:2] + only('BAT')[:8] + only('BWL')[:7]


def test_team_on_field_picks_twelve_with_emergencies_and_pins(server, page):
    _seed(page, _full_squad())
    page.goto(server + '#/team?field=2')
    field, bench = page.locator('#field tbody tr'), page.locator('#bench tbody tr')
    expect(field).to_have_count(12)
    expect(bench).to_have_count(5)
    expect(field.locator('td:first-child')).to_have_text(['WKP'] + ['BAT'] * 5 + ['BWL'] * 5 + ['FLX'])
    expect(page.locator('#fround a[style]')).to_have_text('R2')
    ems = bench.locator('.pill', has_text='E ')
    assert 1 <= ems.count() <= 3
    expect(field.locator('.pill', has_text=re.compile(r'^C$'))).to_have_count(1)

    first = field.nth(1).locator('td.name a').inner_text()
    field.nth(1).locator('button[data-pin]').click()
    expect(bench.filter(has_text=first)).to_contain_text('kept off')
    expect(field.filter(has_text=first)).to_have_count(0)
    bench.filter(has_text=first).locator('button', has_text='Auto').click()
    expect(field.filter(has_text=first)).to_have_count(1)

    capt = field.nth(5).locator('td.name a').inner_text()
    field.nth(5).locator('button[data-cap]').click()
    expect(field.filter(has_text=capt).locator('.pill', has_text=re.compile(r'^C$'))).to_have_count(1)
    assert json.loads(page.evaluate("localStorage.getItem('scbbl-captain')")) == {'2': _squad_pid_by_name(capt)}


def _squad_pid_by_name(name):
    sq = json.loads((ROOT / 'data' / 'squads.json').read_text(encoding='utf-8'))
    return next(r['pid'] for rs in sq['teams'].values() for r in rs if r['n'] == name)


def test_trades_are_free_before_the_lockout(server, page):
    marsh = _squad_pid('SCO', 'Mitchell Marsh')
    _seed(page, [marsh])
    page.goto(server + '#/team?out=' + marsh)
    expect(page.locator('#trades')).to_contain_text('Changes are free until the first lockout')
    page.locator('#opts button[data-in]').first.click()
    assert page.evaluate("localStorage.getItem('scbbl-trades')") is None


def test_trades_count_after_the_lockout_with_undo_boost_and_limit(server, page):
    from datetime import datetime, timezone
    page.clock.set_fixed_time(datetime(2026, 12, 21, 0, 0, tzinfo=timezone.utc))  # round 2
    marsh = _squad_pid('SCO', 'Mitchell Marsh')
    _seed(page, [marsh])
    page.goto(server + '#/team?out=' + marsh)
    expect(page.locator('#tround')).to_have_text('0/3')
    page.locator('#opts button[data-in]').first.click()
    expect(page.locator('#tround')).to_have_text('1/3')
    expect(page.locator('#tseason')).to_have_text('1/26')
    expect(page.locator('#tleft')).to_have_text('25')
    expect(page.locator('#tlog tbody tr')).to_have_count(1)
    expect(page.locator('#tlog tbody tr').first).to_contain_text('R2')

    page.click('#tlog button:has-text("Undo")')
    expect(page.locator('#tround')).to_have_text('0/3')
    expect(page.locator('#team tbody tr', has_text='Mitchell Marsh')).to_have_count(1)

    page.click('#trades button[data-boost="on"]')
    expect(page.locator('#tround')).to_have_text('0/4')
    expect(page.locator('#tboosts')).to_have_text('1/2')
    page.click('#trades button[data-boost="off"]')
    expect(page.locator('#tboosts')).to_have_text('2/2')

    full = [{'round': 2, 'out': 'a', 'in': 'b'}] * 3
    page.evaluate(f"localStorage.setItem('scbbl-trades', JSON.stringify({{trades: {json.dumps(full)}, boosts: []}}))")
    page.goto(server + '#/team?out=' + marsh)
    expect(page.locator('#notrade')).to_contain_text('No trades left in round 2')
    expect(page.locator('#opts button[data-in]').first).to_be_disabled()


def test_no_trades_in_round_1(server, page):
    from datetime import datetime, timezone
    page.clock.set_fixed_time(datetime(2026, 12, 14, 0, 0, tzinfo=timezone.utc))
    marsh = _squad_pid('SCO', 'Mitchell Marsh')
    _seed(page, [marsh])
    page.goto(server + '#/team?out=' + marsh)
    expect(page.locator('#tround')).to_have_text('0/0')
    expect(page.locator('#tleft')).to_have_text('26')
    expect(page.locator('#notrade')).to_contain_text('no trades in round 1')
    expect(page.locator('#opts button[data-in]').first).to_be_disabled()
    expect(page.locator('#trades button[data-boost]')).to_have_count(0)


SC_TEAM = json.loads((ROOT / 'tests' / 'fixtures' / 'sc_statsPlayers.json').read_text(encoding='utf-8'))


def _sc_pid(sc_id):
    return next(pid for pid, p in _sc_players().items() if p['id'] == sc_id)


def _bookmarklet(page, server):
    from urllib.parse import unquote
    page.goto(server + '#/team')
    href = page.locator('#scbm').get_attribute('href')
    assert href.startswith('javascript:')
    return unquote(href[len('javascript:'):])


def _check_imported(page, server):
    on = {_sc_pid(p['player_id']) for p in SC_TEAM['players'] if p['picked'] != 'false'}
    capt = _sc_pid(next(p['player_id'] for p in SC_TEAM['players'] if p['picked'] == 'capt'))
    imp = page.locator('#import')
    expect(imp).to_contain_text('round 1')
    expect(imp).to_contain_text('17 players, 12 on field')
    imp.locator('button[data-import]').click()
    expect(page).to_have_url(server + '#/team?field=1')
    expect(page.locator('.stat').first).to_contain_text('17/17')
    assert json.loads(page.evaluate("localStorage.getItem('scbbl-captain')")) == {'1': capt}
    pins = json.loads(page.evaluate("localStorage.getItem('scbbl-field')"))['1']
    assert {pid for pid, v in pins.items() if v == 'in'} == on and len(pins) == 17
    expect(page.locator('#field tbody tr')).to_have_count(12)
    expect(page.locator('#field .pill', has_text=re.compile(r'^C$'))).to_have_count(1)
    page.click('#unpin')
    expect(page.locator('#unpin')).to_have_count(0)
    assert json.loads(page.evaluate("localStorage.getItem('scbbl-field')"))['1'] == {}


def test_bookmarklet_imports_the_team_from_a_logged_in_supercoach_page(server, page):
    marsh = _squad_pid('SCO', 'Mitchell Marsh')
    _seed(page, [marsh])
    code = _bookmarklet(page, server)
    auth, decoy = [], []

    def fake_sc(route):
        if 'statsPlayers' in route.request.url:
            auth.append(route.request.headers.get('authorization'))
            if auth[-1] == 'Bearer tok':
                return route.fulfill(json=SC_TEAM)
            return route.fulfill(status=401, json={'message': 'bad credentials'})
        # A third-party script on the page loads a lookalike URL last; the token must not go to it.
        route.fulfill(content_type='text/html', body="""<script>
            localStorage.setItem('VMLS:news:accessToken', 'tok');
            fetch('/2026/api/bbl/classic/v1/userteams/1/statsPlayers?round=1', {headers: {Authorization: 'Bearer tok'}})
              .then(() => fetch('https://evil.test/2026/api/bbl/classic/v1/userteams/2/statsPlayers?round=1'));</script>""")
    page.route('https://www.supercoach.com.au/**', fake_sc)
    page.route('https://evil.test/**', lambda r: (decoy.append(r.request.headers.get('authorization')), r.fulfill(json=SC_TEAM, headers={'access-control-allow-origin': '*'})))
    page.goto('https://www.supercoach.com.au/2026/bbl/classic/team')
    page.wait_for_function("performance.getEntriesByType('resource').filter(e => e.name.includes('statsPlayers')).length >= 2")
    page.evaluate('c => { (0, eval)(c); }', code)
    expect(page).to_have_url(re.compile(r'#/team\?r=1&sc='))
    assert auth == ['Bearer tok', 'Bearer tok']
    assert decoy == [None]
    assert 'tok' not in page.url
    expect(page.locator('#import')).to_contain_text('This replaces your squad of 1')
    _check_imported(page, server)


def test_bookmarklet_explains_when_not_on_supercoach_or_not_on_the_team_page(server, page):
    code = _bookmarklet(page, server)
    msgs = []
    page.on('dialog', lambda d: (msgs.append(d.message), d.dismiss()))
    page.evaluate('c => (0, eval)(c)', code)
    page.route('https://www.supercoach.com.au/**', lambda r: r.fulfill(content_type='text/html', body='<p>home</p>'))
    page.goto('https://www.supercoach.com.au/2026/bbl/classic/')
    page.evaluate('c => (0, eval)(c)', code)
    assert msgs == ['Open your team page on supercoach.com.au first, logged in, then click this bookmark.',
                    'Open or reload your team page in SuperCoach BBL, then click this bookmark again.']


def test_clicking_a_bookmarklet_on_the_site_does_nothing(server, page):
    # Without preventDefault the CSP blocks the javascript: URL, which shows up as a violation.
    page.add_init_script(CSP_WATCH)
    msgs = []
    page.on('dialog', lambda d: (msgs.append(d.message), d.dismiss()))
    page.goto(server + '#/team')
    page.click('#importhelp summary')
    page.click('#scbm')
    page.wait_for_timeout(200)
    assert page.evaluate('window.csp') == []
    page.goto(server.replace('index.html', 'tools.html'))
    page.click('#scsave')
    page.wait_for_timeout(200)
    assert page.evaluate('window.csp') == [] and msgs == []


def test_pasted_statsplayers_response_imports_the_team(server, page):
    _seed(page, [])
    page.goto(server + '#/team')
    page.click('#importhelp summary')
    page.fill('#scpaste', '{"not": "it"}')
    page.click('#scpastego')
    expect(page.locator('#scpasteerr')).to_contain_text("isn't a statsPlayers response")
    page.fill('#scpaste', json.dumps(SC_TEAM))
    page.click('#scpastego')
    expect(page.locator('#import')).not_to_contain_text('replaces')
    _check_imported(page, server)


def test_visit_counts_send_the_page_name_only(page):
    def site(route):
        rel = route.request.url.split('.au/', 1)[1].split('#')[0].split('?')[0] or 'index.html'
        f = ROOT / rel
        if not f.is_file():
            return route.fulfill(status=404, body='')
        route.fulfill(body=f.read_bytes(), content_type={'.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml'}.get(f.suffix, 'text/html'))
    page.route('https://bbl.fantasyplanner.au/**', site)
    # Before the forecast window, so the planner doesn't fetch the forecast this test aborts.
    page.clock.set_fixed_time('2026-11-05T00:00:00Z')
    held = []
    page.route('https://bbl.fantasyplanner.au/goatcounter.js', lambda r: held.append(r))
    page.route(re.compile(r'https://(api\.open-meteo\.com|apiv2\.cricket\.com\.au)/.*'), lambda r: r.abort())
    page.goto('https://bbl.fantasyplanner.au/#/team?r=1&sc=98:true,8:vice')
    expect(page.locator('#import')).to_be_visible()
    page.goto('https://bbl.fantasyplanner.au/#/planner')
    expect(page.locator('#app h2').first).to_have_text('Doubles and byes')
    assert len(held) == 1, 'the counter script loads once, after the first page'
    held[0].fulfill(content_type='text/javascript', body="""
        const me = document.currentScript;
        window.counts = [[me.dataset.goatcounter, JSON.parse(me.dataset.goatcounterSettings).no_onload]];
        window.goatcounter = { count: v => window.counts.push(v.path) };""")
    page.wait_for_function('() => window.counts && window.counts.length >= 3')
    page.click('#tabs a[data-tab=roles]')
    page.wait_for_function('() => window.counts.length >= 4')
    assert page.evaluate('window.counts') == [['https://scbbl.goatcounter.com/count', True], '/team', '/planner', '/roles']


def test_the_real_counter_script_sends_under_the_content_security_policy(page):
    def site(route):
        rel = route.request.url.split('.au/', 1)[1].split('#')[0].split('?')[0] or 'index.html'
        f = ROOT / rel
        if not f.is_file():
            return route.fulfill(status=404, body='')
        route.fulfill(body=f.read_bytes(), content_type={'.js': 'text/javascript', '.json': 'application/json'}.get(f.suffix, 'text/html'))
    page.route('https://bbl.fantasyplanner.au/**', site)
    sent = []
    page.route('https://scbbl.goatcounter.com/**', lambda r: (sent.append(r.request.url), r.fulfill(status=200, body='')))
    page.route(re.compile(r'https://(api\.open-meteo\.com|apiv2\.cricket\.com\.au)/.*'), lambda r: r.abort())
    page.add_init_script(CSP_WATCH)
    page.goto('https://bbl.fantasyplanner.au/#/roles')
    expect(page.locator('#app h2').first).to_have_text('Roles and news')
    for _ in range(30):
        if sent:
            break
        page.wait_for_timeout(100)
    assert page.evaluate('window.csp') == []
    assert len(sent) == 1 and 'p=%2Froles' in sent[0], sent


def _with_stat_round(path, n, owned):
    players = json.loads(path.read_text(encoding='utf-8'))
    for p in players:
        for s in p['player_stats']:
            s['round'], s['owned'] = n, owned
    return json.dumps(players)


def _save_bookmark(page, server):
    from urllib.parse import unquote
    page.goto(server.replace('index.html', 'tools.html'))
    href = page.locator('#scsave').get_attribute('href')
    assert href.startswith('javascript:')
    return unquote(href[len('javascript:'):])


@pytest.mark.parametrize('owned', [12.3, None], ids=['with-ownership', 'no-ownership'])
def test_save_prices_bookmark_downloads_the_three_raw_files(server, page, owned):
    code = _save_bookmark(page, server)
    raw = ROOT / 'curated' / 'sc_raw'
    players_body = _with_stat_round(raw / 'players-round1.json', 1, owned)
    auth, asked, msgs = [], [], []
    page.on('dialog', lambda d: (msgs.append(d.message), d.dismiss()))

    def fake_sc(route):
        url = route.request.url
        if '/v1/players-cf' in url:
            auth.append(route.request.headers.get('authorization'))
            asked.append(re.search(r'round=(\d+)', url)[1])
            return route.fulfill(content_type='application/json', body=players_body)
        for key, name in (('settings', 'settings.json'), ('real_fixture', 'fixture.json')):
            if f'/v1/{key}' in url:
                auth.append(route.request.headers.get('authorization'))
                return route.fulfill(content_type='application/json', body=(raw / name).read_text(encoding='utf-8'))
        route.fulfill(content_type='text/html', body="""<script>
            localStorage.setItem('VMLS:news:accessToken', JSON.stringify('tok'));
            fetch('/2026/api/bbl/classic/v1/players-cf?embed=notes%2Codds%2Cplayer_stats%2Cpositions&round=0&xredir=1', {headers: {Authorization: 'Bearer tok'}})
              .then(() => fetch('https://evil.test/2026/api/bbl/classic/v1/players-cf?embed=player_stats'));</script>""")
    decoy = []
    page.route('https://www.supercoach.com.au/**', fake_sc)
    page.route('https://evil.test/**', lambda r: (decoy.append(r.request.headers.get('authorization')), r.fulfill(json=[], headers={'access-control-allow-origin': '*'})))
    page.goto('https://www.supercoach.com.au/2026/bbl/classic/team')
    page.wait_for_function("performance.getEntriesByType('resource').filter(e => e.name.includes('players-cf')).length >= 2")
    auth.clear(), asked.clear()
    got = []
    page.on('download', lambda d: got.append(d))
    page.evaluate('c => { (0, eval)(c); }', code)
    for _ in range(30):
        if len(got) == 3:
            break
        page.wait_for_timeout(100)
    assert auth == ['Bearer tok'] * 3
    assert decoy == [None]
    assert asked == ['1'], "the page asked for round 0, but only settings' next_round carries ownership"
    assert sorted(d.suggested_filename for d in got) == ['fixture.json', 'players-round1.json', 'settings.json']
    page.wait_for_timeout(200)
    assert msgs == ([] if owned else ['Saved, but SuperCoach sent no ownership for round 1.'])
    for d in got:
        name = d.suggested_filename
        want = players_body if name.startswith('players') else (raw / name).read_text(encoding='utf-8')
        assert json.loads(pathlib.Path(d.path()).read_text(encoding='utf-8')) == json.loads(want)


@pytest.mark.parametrize('broken, body, status, token, want', [
    ('settings', '', 200, True, 'settings answered 200 with nothing in it. Reload the page and try again.'),
    ('real_fixture', '', 204, True, 'real_fixture answered 204 with nothing in it. Reload the page and try again.'),
    ('players-cf', '<html>', 200, True, 'players-cf answered 200 with something that is not JSON. Reload the page and try again.'),
    ('settings', '', 401, False, 'settings answered 401. No SuperCoach login was found, so log in first. Reload the page and try again.'),
    ('settings', '', 401, 'odd', 'settings answered 401. A SuperCoach login was found but could not be read. Reload the page and try again.'),
], ids=['empty-settings', 'no-content-fixture', 'html-players', 'logged-out', 'unreadable-login'])
def test_save_prices_bookmark_names_the_endpoint_that_sent_no_json(server, page, broken, body, status, token, want):
    code = _save_bookmark(page, server)
    raw = ROOT / 'curated' / 'sc_raw'
    msgs, got = [], []
    page.on('dialog', lambda d: (msgs.append(d.message), d.dismiss()))
    page.on('download', lambda d: got.append(d))

    def fake_sc(route):
        url = route.request.url
        for key, name in (('settings', 'settings.json'), ('real_fixture', 'fixture.json'), ('players-cf', 'players-round1.json')):
            if f'/v1/{key}' in url:
                if key == broken:
                    return route.fulfill(status=status, content_type='application/json', body=body)
                return route.fulfill(content_type='application/json', body=(raw / name).read_text(encoding='utf-8'))
        stored = {True: "JSON.stringify('tok')", 'odd': "JSON.stringify({jwt: 'tok'})"}.get(token)
        route.fulfill(content_type='text/html', body=(
            f"<script>localStorage.setItem('VMLS:news:accessToken', {stored})</script>" if stored else ''))
    page.route('https://www.supercoach.com.au/**', fake_sc)
    page.goto('https://www.supercoach.com.au/2026/bbl/classic/team')
    page.evaluate('c => { (0, eval)(c); }', code)
    for _ in range(30):
        if msgs:
            break
        page.wait_for_timeout(100)
    assert msgs == ['Save failed: ' + want] and got == []
    assert all(f'status of {status}' in e for e in page.errors)
    page.errors.clear()


def test_save_prices_bookmark_refuses_off_supercoach(server, page):
    code = _save_bookmark(page, server)
    msgs = []
    page.on('dialog', lambda d: (msgs.append(d.message), d.dismiss()))
    page.evaluate('c => (0, eval)(c)', code)
    assert msgs == ['Open SuperCoach BBL first, logged in, then click this bookmark.']


def test_availability_lists_ruled_out_player(server, page):
    page.goto(server + '#/availability')
    expect(page.locator('#app table tbody tr', has_text='Jason Behrendorff')).to_have_count(1)


CA_CARD = ROOT / 'tests' / 'fixtures' / 'ca_scorecard_23768.json'
CA_COMMENTS = json.loads((ROOT / 'tests' / 'fixtures' / 'ca_comments_23768.json').read_text(encoding='utf-8'))
HEA_V_SCO = 40745  # BBL|16 fixture the BBL|15 HEA v SCO scorecard is replayed against
EMPTY_CARD = json.dumps({'players': [], 'fixture': {'innings': []}})


def _mock_feeds(page, rain_at=None):
    """Replay a finished CA scorecard for HEA v SCO (others pre-toss) and serve a dry forecast."""
    def ca(route):
        url = route.request.url
        if 'views/comments' in url:
            n = int(re.search(r'inningNumber=(\d)', url)[1])
            overs = next(i['overs'] for i in CA_COMMENTS if i['inningNumber'] == n) if f'fixtureId={HEA_V_SCO}' in url else []
            body = json.dumps({'inning': {'overs': overs}, 'nextPage': ''})
        else:
            body = CA_CARD.read_text(encoding='utf-8') if f'fixtureId={HEA_V_SCO}' in url else EMPTY_CARD
        route.fulfill(body=body, content_type='application/json', headers={'access-control-allow-origin': '*'})

    def meteo(route):
        times = [f'2027-01-{d:02d}T{h:02d}:00' for d in range(7, 23) for h in range(24)]
        wet = {rain_at} if isinstance(rain_at, str) else set(rain_at or ())
        p = [70 if t in wet else 5 for t in times]
        route.fulfill(body=json.dumps({'hourly': {'time': times, 'precipitation_probability': p,
                                                  'precipitation': [0.0] * len(times)}}),
                      content_type='application/json', headers={'access-control-allow-origin': '*'})
    page.route('https://apiv2.cricket.com.au/**', ca)
    page.route('https://api.open-meteo.com/**', meteo)


def test_matches_list_shows_every_fixture_with_historical_rain(server, page):
    page.clock.set_fixed_time('2026-11-05T00:00:00Z')
    _mock_feeds(page)
    page.goto(server + '#/matches')
    rows = page.locator('#mtable tbody tr')
    expect(rows).to_have_count(44)
    expect(rows.first.locator('.rain')).to_contain_text('hist.')
    expect(page.locator('#tabs a.on')).to_have_text('Matches')
    expect(page.locator('#alerts')).to_contain_text('Match alerts')
    expect(page.locator('#alerts a[href*="ntfy"]')).to_have_count(0)


PUSH_API = 'https://scbbl-notify.donkalot.workers.dev'
FAKE_ENDPOINT = 'https://fcm.googleapis.com/fcm/send/smoke'
# Headless Chromium can't reach a real push service, so stand in for the service worker's PushManager.
FAKE_PUSH = """(() => {
  let perm = %(perm)s, current = null;
  const pm = {
    getSubscription: async () => current,
    subscribe: async o => (current = {
      endpoint: %(endpoint)s, options: { applicationServerKey: o.applicationServerKey.buffer },
      toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'p', auth: 'a' } }; },
      unsubscribe: async () => { current = null; return true; },
    }),
  };
  Object.defineProperty(navigator, 'serviceWorker', { value: { register: async () => ({}), ready: Promise.resolve({ pushManager: pm }) } });
  Object.defineProperty(Notification, 'permission', { get: () => perm });
  Notification.requestPermission = async () => (perm = 'granted');
  %(extra)s
})();"""


def _fake_push(page, perm='default', extra=''):
    page.add_init_script(FAKE_PUSH % {'perm': json.dumps(perm), 'endpoint': json.dumps(FAKE_ENDPOINT), 'extra': extra})
    calls = []

    def api(route):
        req = route.request
        path = req.url[len(PUSH_API):]
        calls.append((path, req.post_data_json if req.method == 'POST' else None))
        if path == '/vapid':
            body, status = {'key': 'BA' + 'A' * 85}, 200
        elif path == '/subscribe':
            body, status = {'teams': req.post_data_json['teams']}, 201 if len([c for c in calls if c[0] == '/subscribe']) == 1 else 200
        else:
            body, status = {}, 200
        route.fulfill(status=status, body=json.dumps(body), content_type='application/json',
                      headers={'access-control-allow-origin': '*'})
    page.route(PUSH_API + '/**', api)
    return calls


def test_alerts_turn_on_change_teams_and_turn_off(server, page):
    page.clock.set_fixed_time('2026-11-05T00:00:00Z')
    _mock_feeds(page)
    _seed(page, [_squad_pid('HEA', 'Jack Wildermuth'), _squad_pid('SCO', 'Mitchell Marsh')])
    calls = _fake_push(page)
    page.goto(server + '#/matches')
    box = lambda v: page.locator(f'#alert-teams input[value="{v}"]')
    expect(box('HEA')).to_be_checked()
    expect(box('SCO')).to_be_checked()
    expect(box('all')).not_to_be_checked()
    expect(page.locator('#alert-state')).to_have_text('Off')
    page.click('#alert-on')
    expect(page.locator('#alert-msg')).to_have_text('Alerts are on. A confirmation notification should arrive now.')
    expect(page.locator('#alert-state')).to_have_text('On')
    assert calls[0] == ('/vapid', None)
    assert calls[1] == ('/subscribe', {'subscription': {'endpoint': FAKE_ENDPOINT, 'keys': {'p256dh': 'p', 'auth': 'a'}},
                                       'teams': ['HEA', 'SCO']})
    box('all').check()
    expect(box('HEA')).not_to_be_checked()
    page.click('#alert-save')
    expect(page.locator('#alert-msg')).to_have_text('Saved.')
    assert calls[-1][1]['teams'] == ['all']
    box('SIX').check()
    expect(box('all')).not_to_be_checked()
    page.click('#alert-squad')
    expect(box('SIX')).not_to_be_checked()
    expect(box('HEA')).to_be_checked()
    page.click('#alert-off')
    expect(page.locator('#alert-msg')).to_have_text('Alerts are off.')
    expect(page.locator('#alert-state')).to_have_text('Off')
    assert calls[-1] == ('/unsubscribe', {'endpoint': FAKE_ENDPOINT, 'auth': 'a'})
    assert page.evaluate("localStorage.getItem('scbbl-alerts')") is None


def test_alerts_explain_a_network_block_page(server, page):
    # Cisco Umbrella answers for the Worker with a CORS-enabled redirect to an HTML block page that returns 200.
    page.clock.set_fixed_time('2026-11-05T00:00:00Z')
    _mock_feeds(page)
    _fake_push(page)
    page.route(PUSH_API + '/**', lambda r: r.fulfill(status=200, body='<html>blocked</html>', content_type='text/html',
                                                     headers={'access-control-allow-origin': '*'}))
    page.goto(server + '#/matches')
    page.click('#alert-on')
    expect(page.locator('#alert-msg')).to_contain_text("Couldn't reach the alerts server")
    expect(page.locator('#alert-state')).to_have_text('Off')


def test_alerts_explain_blocked_and_unsupported_browsers(server, browser):
    for perm, extra, text in [('denied', '', 'Notifications are blocked'),
                              ('default', 'delete window.PushManager;', "can't receive push alerts")]:
        ctx = browser.new_context(service_workers='block')
        pg = ctx.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.clock.set_fixed_time('2026-11-05T00:00:00Z')
        _mock_feeds(pg)
        _fake_push(pg, perm, extra)
        pg.goto(server + '#/matches')
        expect(pg.locator('#alerts')).to_contain_text(text)
        expect(pg.locator('#alert-on')).to_have_count(0)
        assert errors == []
        ctx.close()


def test_match_page_scores_the_replayed_scorecard(server, page):
    page.clock.set_fixed_time('2027-01-07T00:00:00Z')
    _mock_feeds(page, rain_at='2027-01-08T10:00')
    wild = _squad_pid('HEA', 'Jack Wildermuth')
    page.add_init_script(f"localStorage.setItem('scbbl-squad', JSON.stringify(['{wild}']))")
    page.add_init_script(CSP_WATCH)
    page.goto(server + f'#/match/{HEA_V_SCO}')
    expect(page.locator('#rain .pill')).to_have_text('Rain High')
    def row_of(n):
        return page.locator('#live tbody tr').filter(has=page.locator('td.name', has_text=n))
    row = row_of('Jack Wildermuth')
    expect(row.locator('td.sc')).to_have_text('179')
    expect(row_of('Cooper Connolly').locator('td.sc')).to_have_text('114')
    expect(page.locator('#live h3')).to_have_count(2)
    expect(page.locator('#mtotal')).to_have_text('179')
    row.locator('button[data-cap]').click()
    expect(row.locator('td.sc')).to_have_text('358 ×2')
    expect(page.locator('#mtotal')).to_have_text('358')
    expect(page.locator('#rtotal')).to_have_text('358')
    assert page.evaluate('window.csp') == []


def test_planner_marks_forecast_rain_for_teams_and_my_squad(server, page):
    page.clock.set_fixed_time('2027-01-07T00:00:00Z')
    # HEA v SCO is a day out; HEA v THU on 17 Jan is 10 days out, so its forecast is early.
    _mock_feeds(page, rain_at=('2027-01-08T10:00', '2027-01-17T09:00'))
    page.add_init_script(f"localStorage.setItem('scbbl-squad', JSON.stringify(['{_squad_pid('HEA', 'Jack Wildermuth')}']))")
    rounds = json.loads((ROOT / 'data' / 'rounds.json').read_text())['rounds']
    rnd = lambda d: next(r['round'] for r in rounds if r['start'] <= d <= r['end'])
    near, far = rnd('2027-01-08'), rnd('2027-01-17')
    page.goto(server + f'#/planner?r={near}')
    expect(page.locator(f'#rtable tr[data-id="{HEA_V_SCO}"] .rain .pill')).to_have_text('Rain High')
    expect(page.locator('#rtable .rain .pill').first).to_be_visible()
    expect(page.locator(f'td[data-t="HEA"][data-r="{near}"] i.wet.High:not(.early)')).to_have_count(1)
    expect(page.locator(f'td[data-t="SCO"][data-r="{near}"] i.wet.High')).to_have_count(1)
    expect(page.locator(f'td[data-t="HEA"][data-r="{far}"] i.wet.High.early')).to_have_count(1)
    expect(page.locator(f'td[data-t="REN"][data-r="{near}"] i.wet')).to_have_count(0)
    mine = page.locator(f'td[data-pid][data-r="{near}"]')
    expect(mine.locator('i.wet.High')).to_have_count(1)
    expect(mine).to_have_attribute('title', re.compile(r'HEA v SCO 8 Jan: rain High, 70%'))
    expect(page.locator(f'#atrisk td[data-r="{near}"]')).to_have_text('1 High')
    expect(page.locator(f'#atrisk td[data-r="{far}"]')).to_have_text('1 High')
    # Rounds beyond the forecast stay blank rather than claiming 0.
    expect(page.locator(f'#atrisk td[data-r="{near - 1}"]')).to_have_text('')


def test_match_page_before_the_toss_shows_squads(server, page):
    page.clock.set_fixed_time('2026-11-05T00:00:00Z')
    _mock_feeds(page)
    page.goto(server + '#/match/40719')
    expect(page.locator('#live')).to_contain_text("XIs aren't named yet")
    expect(page.locator('#live .stat')).to_have_count(2)
    expect(page.locator('#rain')).to_contain_text('Too far out for a forecast')


def test_live_match_polls_until_you_leave(server, page):
    live = json.loads(CA_CARD.read_text(encoding='utf-8'))
    live['fixture'].update(isCompleted=False, isLive=True, resultText='')
    hits = []

    def ca(route):
        if 'views/comments' in route.request.url:
            return route.fallback()
        if f'fixtureId={HEA_V_SCO}' in route.request.url:
            hits.append(route.request.url)
        route.fulfill(body=json.dumps(live), content_type='application/json', headers={'access-control-allow-origin': '*'})
    page.clock.install(time='2027-01-08T09:00:00Z')
    _mock_feeds(page)
    page.route('https://apiv2.cricket.com.au/**', ca)
    page.goto(server + f'#/match/{HEA_V_SCO}')
    expect(page.locator('#live')).to_contain_text('Updates every 30 seconds')
    expect(page.locator('#live tbody tr').filter(has=page.locator('td.name', has_text='Jack Wildermuth'))
           .locator('.pill.ok')).to_have_text('in')
    first = len(hits)
    page.clock.run_for(31_000)
    page.wait_for_timeout(300)
    assert len(hits) == first + 1
    page.evaluate("location.hash = '#/matches'")
    expect(page.locator('#mtable tr[data-id="%d"] .status' % HEA_V_SCO)).to_contain_text('HEA 258/2')
    left = len(hits)
    page.clock.run_for(65_000)
    page.wait_for_timeout(300)
    assert len(hits) == left


def test_pitch_note_on_the_match_list_and_match_page(server, page):
    page.clock.set_fixed_time('2026-11-05T00:00:00Z')
    _mock_feeds(page)
    page.goto(server + '#/matches')
    # The Gabba has run clearly high over the last 5 seasons; Chennai has no BBL history.
    expect(page.locator(f'#mtable tr[data-id="{HEA_V_SCO}"] .pitch')).to_contain_text('Batting-friendly')
    expect(page.locator('#mtable tr[data-id="40719"] .pitch')).to_have_text('')
    page.goto(server + f'#/match/{HEA_V_SCO}')
    pitch = page.locator('#pitch')
    expect(pitch).to_contain_text('batting-friendly')
    expect(pitch).to_contain_text('2025/26:')
    expect(pitch).to_contain_text('No full games here yet this season (2026/27)')
    expect(pitch).to_contain_text('background, not a predictor')
    page.goto(server + '#/match/40719')
    expect(page.locator('#pitch')).to_contain_text('No full BBL games here')


def test_pages_serves_files_as_is():
    # Without it Jekyll would turn any committed file with front matter into a page on the site.
    assert (ROOT / '.nojekyll').exists()
