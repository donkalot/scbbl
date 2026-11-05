"""End-to-end smoke test: serve the repo root and drive every tab in headless Chromium."""
import http.server
import json
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
    cell = page.locator('#ptable tbody tr', has_text='Jonny Bairstow').locator('td').nth(4)
    expect(cell).to_contain_text('(')


def test_squad_add_shows_in_planner(server, page):
    page.goto(server + '#/players')
    page.fill('#q', 'marsh')
    row = page.locator('#ptable tbody tr', has_text='Mitchell Marsh')
    row.locator('button[data-squad]').click()
    expect(row.locator('button[data-squad]')).to_have_text('✓')
    page.goto(server + '#/planner')
    expect(page.locator('#app table').nth(1).locator('tbody tr', has_text='Mitchell Marsh')).to_have_count(1)


def test_availability_lists_ruled_out_player(server, page):
    page.goto(server + '#/availability')
    expect(page.locator('#app table tbody tr', has_text='Jason Behrendorff')).to_have_count(1)


CA_CARD = ROOT / 'tests' / 'fixtures' / 'ca_scorecard_23768.json'
HEA_V_SCO = 40745  # BBL|16 fixture the BBL|15 HEA v SCO scorecard is replayed against
EMPTY_CARD = json.dumps({'players': [], 'fixture': {'innings': []}})


def _mock_feeds(page, rain_at=None):
    """Replay a finished CA scorecard for HEA v SCO (others pre-toss) and serve a dry forecast."""
    def ca(route):
        body = CA_CARD.read_text(encoding='utf-8') if f'fixtureId={HEA_V_SCO}' in route.request.url else EMPTY_CARD
        route.fulfill(body=body, content_type='application/json', headers={'access-control-allow-origin': '*'})

    def meteo(route):
        times = [f'2027-01-{d:02d}T{h:02d}:00' for d in range(7, 23) for h in range(24)]
        p = [70 if t == rain_at else 5 for t in times]
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
    expect(row.locator('td.sc')).to_have_text('182')
    expect(row_of('Cooper Connolly').locator('td.sc')).to_have_text('118')
    expect(page.locator('#live h3')).to_have_count(2)
    expect(page.locator('#mtotal')).to_have_text('182')
    row.locator('button[data-cap]').click()
    expect(row.locator('td.sc')).to_have_text('364 ×2')
    expect(page.locator('#mtotal')).to_have_text('364')
    expect(page.locator('#rtotal')).to_have_text('364')


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
