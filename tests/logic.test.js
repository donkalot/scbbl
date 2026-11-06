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
  availability.links.push({ pid: 'p2', event: 't2', likely: true });
  assert.deepEqual(L.eventsFor('p2', availability).map(e => e.likely), [true]);
  assert.equal(L.eventsFor('p1', availability)[0].likely, false);
  assert.equal(L.playerRounds('HEA', 'p2', grid, availability)[1].available, 1);
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

const POSITIONS = { WKP: { squad: 1 }, BAT: { squad: 2 }, BWL: { squad: 1 }, FLX: { squad: 1 } };
const P = (pid, ...pos) => ({ pid, pos, price: 100 });

test('slotFit moves a dual-position player to free a seat, and FLX takes the overflow', () => {
  const players = [P('wb', 'WKP', 'BAT'), P('b1', 'BAT'), P('b2', 'BAT'), P('w2', 'WKP')];
  const f = L.slotFit(players, POSITIONS);
  assert.deepEqual(f.unplaced, []);
  assert.deepEqual(f.slots.map(s => s.pos), ['WKP', 'BAT', 'BAT', 'BWL', 'FLX']);
  assert.deepEqual(f.slots.map(s => s.pid).filter(Boolean).sort(), ['b1', 'b2', 'w2', 'wb']);
  for (const s of f.slots) if (s.pid && s.pos !== 'FLX') assert.ok(players.find(p => p.pid === s.pid).pos.includes(s.pos));
  assert.equal(f.slots[3].pid, null);
  const over = L.slotFit([P('w1', 'WKP'), P('w2', 'WKP'), P('w3', 'WKP')], POSITIONS);
  assert.deepEqual([over.slots.find(s => s.pos === 'FLX').pid, over.unplaced], ['w2', ['w3']]);
});

test('fitting keeps affordable players who leave everyone a seat', () => {
  const squad = [P('w1', 'WKP'), P('w2', 'WKP'), P('b1', 'BAT')];
  const pool = [P('w3', 'WKP'), P('b2', 'BAT'), { ...P('x', 'BWL'), price: 500 }, P('y', 'BWL')];
  assert.deepEqual(L.fitting(squad, pool, POSITIONS, 200).map(p => p.pid), ['b2', 'y']);
});

const FIELD = { WKP: { active: 1 }, BAT: { active: 2 }, BWL: { active: 1 }, FLX: { active: 1 } };
const V = (pid, value, ...pos) => ({ pid, pos, value });
const SIDE = [V('w1', 50, 'WKP'), V('w2', 40, 'WKP'), V('wb', 60, 'WKP', 'BAT'), V('b1', 30, 'BAT'), V('b2', 20, 'BAT'),
  V('k1', 70, 'BWL'), V('k2', 10, 'BWL'), V('k3', 0, 'BWL')];
const pids = xs => xs.map(x => x.pid).filter(Boolean).sort();

test('bestField seats the highest values, moving a dual-position player, and picks emergencies from the bench', () => {
  const f = L.bestField(SIDE, FIELD, 3);
  assert.deepEqual(pids(f.seats), ['b1', 'k1', 'w1', 'w2', 'wb']);
  for (const s of f.seats) if (s.pos !== 'FLX') assert.ok(SIDE.find(p => p.pid === s.pid).pos.includes(s.pos));
  assert.deepEqual(f.bench.map(p => p.pid), ['b2', 'k2', 'k3']);
  // k3 has no game, and no bench player can cover WKP.
  assert.deepEqual(f.emergencies.map(s => [s.pos, s.pid]), [['BAT', 'b2'], ['BWL', 'k2']]);
  assert.deepEqual([f.captain, f.vice], ['k1', 'wb']);
  assert.deepEqual(f.unseated, []);
});

test('bestField honours pins, and reports a pinned player with no seat left', () => {
  const f = L.bestField(SIDE, FIELD, 3, { b1: 'out', k3: 'in' });
  assert.deepEqual(pids(f.seats), ['b2', 'k1', 'k3', 'w1', 'wb']);
  const g = L.bestField(SIDE, FIELD, 3, { w1: 'in', w2: 'in', k1: 'out', b1: 'out', b2: 'out', wb: 'out', k2: 'out' });
  assert.deepEqual(pids(g.seats), ['k3', 'w1', 'w2']);
  assert.deepEqual(g.unseated, []);
  const h = L.bestField([...SIDE, V('w3', 5, 'WKP')], FIELD, 3, { w1: 'in', w2: 'in', w3: 'in' });
  assert.deepEqual(h.unseated, ['w3']);
});

test('fieldScore counts the best n and doubles the captain', () => {
  assert.equal(L.fieldScore([30, 70, 50, 60, 40], 4, 70), 290);
});

test('tradeRound is the first round with a match still to finish', () => {
  const rounds = [{ round: 1, start: '2026-12-12', end: '2026-12-19' }, { round: 2, start: '2026-12-20', end: '2026-12-24' }];
  const fx = [
    { stage: 'league', start: '2026-12-14T08:00:00Z', end: '2026-12-14T11:30:00Z' },
    { stage: 'league', start: '2026-12-21T08:00:00Z', end: '2026-12-21T11:30:00Z' },
    { stage: 'final', start: '2027-01-20T08:00:00Z', end: '2027-01-20T11:30:00Z' },
  ];
  assert.equal(L.tradeRound(fx, rounds, Date.parse('2026-12-01T00:00:00Z')), 1);
  assert.equal(L.tradeRound(fx, rounds, Date.parse('2026-12-14T11:31:00Z')), 2);
  assert.equal(L.tradeRound(fx, rounds, Date.parse('2026-12-22T00:00:00Z')), null);
});

test('tradeStatus caps the round at the season total, and a boost adds a trade', () => {
  const rules = { trades_round: 3, trades_total: 26, boosts: 2 };
  const book = { trades: [...Array(23).fill({ round: 1 }), { round: 5 }, { round: 5 }], boosts: [5] };
  assert.deepEqual(L.tradeStatus(book, rules, 5), { used: 25, inRound: 2, roundMax: 4, boosted: true, left: 1, roundLeft: 1, boostsLeft: 1 });
  assert.equal(L.tradeStatus({ trades: [{ round: 6 }], boosts: [] }, rules, 6).roundLeft, 2);
});

test('season line and overs', () => {
  const s = L.seasonLine({ m: 4, sc: 200, inn: 4, no: 1, r: 90, bf: 60, lb: 45, rc: 54 });
  assert.equal(s.avg, 50);
  assert.equal(s.batAvg, 30);
  assert.equal(s.sr, 150);
  assert.equal(s.econ, 54 * 6 / 45);
  assert.equal(s.overs, '7.3');
});

test('sumAggs totals seasons and keeps the best high score and bowling', () => {
  const base = { inn: 0, no: 0, r: 0, bf: 0, lb: 0, rc: 0, wk: 0 };
  const t = L.sumAggs([
    { ...base, m: 3, inn: 3, no: 1, r: 90, bf: 60, hs: 50, hsn: false, bb: [2, 20], lb: 60, rc: 70, wk: 4, sc: 150, scm: 3 },
    { ...base, m: 2, inn: 2, no: 0, r: 40, bf: 40, hs: 50, hsn: true, bb: [2, 15], lb: 0, rc: 0, wk: 0 },
  ]);
  assert.equal(t.m, 5);
  assert.equal(`${t.hs}${t.hsn ? '*' : ''}`, '50*');
  assert.deepEqual(t.bb, [2, 15]);
  assert.equal(t.scm, 3);
  const a = L.aggLine(t);
  assert.equal(a.scAvg, 50);
  assert.equal(a.batAvg, 130 / 4);
  assert.equal(a.hs, '50*');
  assert.equal(a.bb, '2/15');
  assert.equal(a.overs, '10.0');
  assert.equal(L.aggLine({ ...base, m: 1 }).scAvg, null);
});

test('innings text for one and two innings', () => {
  assert.equal(L.battingText([[45, 32, false]]), '45* (32)');
  assert.equal(L.battingText([[12, 20, true], [45, 70, false]]), '12 & 45*');
  assert.equal(L.battingText([]), '');
  assert.equal(L.bowlingText([[24, 31, 2], [12, 20, 1]]), '2/31 & 1/20');
});

const scoring = data('scoring.json');

test('scPoints matches the Python sc_points on every BBL|15 line', () => {
  const lines = data('matches/2025-26.json').flatMap(m => m.lines);
  assert.ok(lines.length > 900);
  for (const l of lines) assert.equal(L.scPoints(l, scoring), l.sc, JSON.stringify(l));
});

test('a CA scorecard plus its ball-by-ball gives the Cricsheet points, apart from shared run-outs', () => {
  const fixture = f => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', f), 'utf8'));
  const card = fixture('ca_scorecard_23768.json');
  const byes = {};
  for (const inn of fixture('ca_comments_23768.json')) {
    for (const o of inn.overs) for (const [k, n] of Object.entries(L.byeDots(o.balls))) byes[k] = (byes[k] || 0) + n;
  }
  assert.equal(Object.values(byes).reduce((s, n) => s + n, 0), 9);
  const idmap = data('idmap.json');
  const cs = data('matches/2025-26.json').find(m => m.id === '1493243').lines;
  const lines = L.caLines(card, byes);
  assert.equal(lines.length, 22);
  let checked = 0;
  for (const l of lines) {
    const c = cs.find(x => x.pid === idmap[l.ca] && !x.sub);
    if (!c) continue;
    checked++;
    assert.equal(l.dots, c.dots, l.name);
    assert.equal(L.scPoints({ ...l, ro: c.ro, ro_solo: c.ro_solo }, scoring), c.sc, l.name);
  }
  assert.equal(checked, 22);
  assert.ok(L.caLines(card).some((l, i) => l.dots > lines[i].dots));
});

test('rain bands from forecast hours and from climatology', () => {
  assert.equal(L.rainRisk([]), null);
  assert.equal(L.rainRisk([{ p: 10, mm: 0 }, { p: 20, mm: 0.1 }]).level, 'Low');
  assert.equal(L.rainRisk([{ p: 35, mm: 0 }]).level, 'Med');
  assert.equal(L.rainRisk([{ p: 20, mm: 2 }, { p: 20, mm: 1.5 }]).level, 'High');
  assert.equal(L.climateRisk({ n: 70, wet: 5, heavy: 1 }).level, 'Low');
  assert.equal(L.climateRisk({ n: 70, wet: 7, heavy: 1 }).level, 'Med');
  assert.equal(L.climateRisk({ n: 70, wet: 14, heavy: 2 }).level, 'High');
});

test('window hours use Open-Meteo end-of-hour labels', () => {
  assert.deepEqual(L.windowHours('2026-12-12T09:10:00Z', '2026-12-12T11:40:00Z'),
    ['2026-12-12T10:00', '2026-12-12T11:00', '2026-12-12T12:00']);
});

test('a SuperCoach team imports as squad, captain and on-field pins, from JSON or the bookmarklet code', () => {
  const resp = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'sc_statsPlayers.json'), 'utf8'));
  const sc = data('sc.json').players;
  const idToPid = Object.fromEntries(Object.entries(sc).map(([pid, r]) => [r.id, pid]));
  const picks = L.scPicks(resp);
  assert.equal(picks.length, 17);
  assert.equal(picks[0].round, 1);
  const t = L.scImport(picks, idToPid);
  assert.equal(t.squad.length, 17);
  assert.deepEqual(t.missing, []);
  assert.equal(sc[t.captain].id, 15);
  assert.equal(Object.values(t.pins).filter(v => v === 'in').length, 12);
  const code = resp.players.map(p => `${p.player_id}:${p.picked}`).join(',');
  assert.deepEqual(L.scImport(L.scPicks(code), idToPid), t);
  assert.deepEqual(L.scImport(L.scPicks('99999:true,15:capt,bad'), idToPid), { squad: [t.captain], captain: t.captain, pins: { [t.captain]: 'in' }, missing: [99999] });
});

test('CA players map by id, then by surname and initial within the squad', () => {
  const rows = [{ pid: 'a', n: 'Jonny Bairstow' }, { pid: 'b', n: 'Tom Curran' }, { pid: 'c', n: 'Sam Curran' }];
  assert.equal(L.matchPid({ ca: 1, name: 'X' }, { 1: 'z' }, rows), 'z');
  assert.equal(L.matchPid({ ca: 2, name: 'Jonathan Bairstow' }, {}, rows), 'a');
  assert.equal(L.matchPid({ ca: 3, name: 'Tom Curran' }, {}, rows), 'b');
  assert.equal(L.matchPid({ ca: 4, name: 'T. Smith' }, {}, rows), null);
});
