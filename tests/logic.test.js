const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const L = require('../logic.js');

const data = f => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', f), 'utf8'));
const fixture = data('fixture.json');
const rounds = data('rounds.json').rounds;

test('localDate converts UTC to the AEDT calendar day', () => {
  assert.equal(L.localDate('2026-12-12T09:10:00Z'), '2026-12-12');
  assert.equal(L.localDate('2026-12-26T13:15:00Z'), '2026-12-27');
});

test('every team has 10 league games across the rounds', () => {
  const grid = L.teamRounds(fixture, rounds);
  for (const t of L.TEAMS) {
    const n = Object.values(grid[t]).reduce((s, g) => s + g.length, 0);
    assert.equal(n, 10, t);
  }
});

test('every league match lands in exactly one round', () => {
  const league = fixture.filter(m => m.stage === 'league');
  assert.ok(league.every(m => L.roundOf(L.localDate(m.start), rounds)));
});

test('availability removes games that fall inside a linked event', () => {
  const grid = {
    HEA: {
      1: [{ start: '2026-12-15T08:15:00Z' }, { start: '2026-12-19T08:15:00Z' }],
      2: [{ start: '2026-12-26T08:15:00Z' }],
    },
  };
  const availability = {
    events: [{ id: 't2', start: '2026-12-17', end: '2026-12-21' }],
    links: [{ pid: 'p1', event: 't2' }],
  };
  const r = L.playerRounds('HEA', 'p1', grid, availability);
  assert.deepEqual([r[1].games, r[1].available, r[2].available], [2, 1, 1]);
  assert.equal(L.playerRounds('HEA', 'other', grid, availability)[1].available, 2);
});

test('projAvg uses the last two seasons, career when that is too thin', () => {
  const p = { s: { '2023/24': { sc: 300, m: 5 }, '2024/25': { sc: 0, m: 0 }, '2025/26': { sc: 120, m: 2 } } };
  assert.equal(L.projAvg(p, ['2023/24', '2024/25', '2025/26']), 420 / 7);
  p.s['2024/25'] = { sc: 200, m: 4 };
  assert.equal(L.projAvg(p, ['2023/24', '2024/25', '2025/26']), 320 / 6);
});

test('captain picks weigh average by available games', () => {
  const e = [
    { pid: 'a', avg: 60, rounds: { 1: { available: 1 } } },
    { pid: 'b', avg: 45, rounds: { 1: { available: 2 } } },
    { pid: 'c', avg: 90, rounds: { 1: { available: 0 } } },
    { pid: 'd', avg: null, rounds: { 1: { available: 2 } } },
  ];
  assert.deepEqual(L.captainPicks(e, 1).map(x => x.pid), ['b', 'a']);
});

test('season line and overs', () => {
  const s = L.seasonLine({ m: 4, sc: 200, inn: 4, no: 1, r: 90, bf: 60, lb: 45, rc: 54 });
  assert.equal(s.avg, 50);
  assert.equal(s.batAvg, 30);
  assert.equal(s.sr, 150);
  assert.equal(s.econ, 54 * 6 / 45);
  assert.equal(s.overs, '7.3');
});
