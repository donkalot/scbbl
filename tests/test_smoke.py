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
    page.goto(server + '#/player/' + _squad_pid('SCO', 'Mitchell Marsh'))
    expect(page.locator('#app h2').first).to_have_text('Mitchell Marsh')
    expect(page.locator('#log tbody tr').first).to_be_visible()
    expect(page.locator('#last5')).not_to_have_text('–')


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
    cell = page.locator('#ptable tbody tr', has_text='Jonny Bairstow').locator('td').nth(7)
    expect(cell).to_contain_text('(')


def test_players_show_supercoach_price_position_and_ownership(server, page):
    pid = _squad_pid('SCO', 'Mitchell Marsh')
    sc = json.loads((ROOT / 'data' / 'sc.json').read_text(encoding='utf-8'))['players'][pid]
    page.goto(server + '#/players?q=marsh')
    expect(page.locator('#app')).to_contain_text('SuperCoach prices and ownership for round')
    cells = page.locator('#ptable tbody tr', has_text='Mitchell Marsh').locator('td')
    expect(cells.nth(3)).to_have_text('/'.join(sc['pos']))
    expect(cells.nth(4)).to_have_text(f"${sc['price'] / 1000:.1f}k")
    expect(cells.nth(5)).to_have_text(f"{sc['own']:.1f}")
    page.select_option('#pos', 'WKP')
    expect(page.locator('#ptable tbody tr', has_text='Mitchell Marsh')).to_have_count(0)
    page.goto(server + '#/player/' + pid)
    expect(page.locator('.stats')).to_contain_text("SC price")
    expect(page.locator('.stats')).to_contain_text(f"{sc['prev'][1]} pts in {sc['prev'][0]}")


def test_squad_add_shows_in_planner(server, page):
    page.goto(server + '#/players')
    page.fill('#q', 'marsh')
    row = page.locator('#ptable tbody tr', has_text='Mitchell Marsh')
    row.locator('button[data-squad]').click()
    expect(row.locator('button[data-squad]')).to_have_text('✓')
    page.goto(server + '#/planner')
    expect(page.locator('#app table').nth(1).locator('tbody tr', has_text='Mitchell Marsh')).to_have_count(1)


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
