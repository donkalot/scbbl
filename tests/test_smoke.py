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
