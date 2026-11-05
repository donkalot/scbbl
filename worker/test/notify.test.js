import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { run, due, resetCache } from '../src/notify.js';

const root = new URL('../../', import.meta.url);
const json = p => JSON.parse(readFileSync(new URL(p, root), 'utf8'));
const DATA = Object.fromEntries(['fixture', 'squads', 'idmap', 'availability'].map(n => [n, json(`data/${n}.json`)]));
const CARD = json('tests/fixtures/ca_scorecard_23768.json');
const EMPTY = { players: [], fixture: { innings: [] } };
const HEA_V_SCO = DATA.fixture.find(m => m.id === 40745);
const START = Date.parse(HEA_V_SCO.start);
const at = mins => START + mins * 60e3;
const ENV = { SITE: 'https://site.test', NTFY: 'https://ntfy.test', TOPIC_PREFIX: 'scbbl' };

function world({ card = EMPTY, failTopic = null, forecast = true } = {}) {
  const kv = new Map();
  const posts = [];
  const w = {
    card, failTopic, posts,
    env: { ...ENV, SENT: { get: async k => kv.get(k) ?? null, put: async (k, v) => { kv.set(k, v); } } },
    kv,
    async fetch(url, opts = {}) {
      const u = String(url);
      const ok = body => ({ ok: true, status: 200, json: async () => body });
      if (u.startsWith(ENV.SITE + '/data/')) return ok(DATA[u.split('/').pop().replace('.json', '')]);
      if (u.startsWith('https://apiv2.cricket.com.au/')) return ok(w.card);
      if (u.startsWith('https://api.open-meteo.com/')) {
        if (!forecast) return { ok: false, status: 500 };
        const time = [], p = [], mm = [];
        for (let h = Math.floor(START / 3600e3) * 3600e3 - 6 * 3600e3; h < START + 12 * 3600e3; h += 3600e3) {
          time.push(new Date(h).toISOString().slice(0, 16)); p.push(40); mm.push(0.2);
        }
        return ok({ hourly: { time, precipitation_probability: p, precipitation: mm } });
      }
      if (u === ENV.NTFY + '/') {
        const body = JSON.parse(opts.body);
        if (body.topic === w.failTopic) return { ok: false, status: 429 };
        posts.push({ ...body, auth: opts.headers.authorization });
        return { ok: true, status: 200 };
      }
      throw new Error('unexpected fetch ' + u);
    },
    tick: mins => run(w.env, at(mins), w.fetch),
  };
  return w;
}

test.beforeEach(resetCache);

test('windows open at T-60, T-30 and T-75 for the XI, and finals with TBC teams never fire', () => {
  assert.deepEqual(due(HEA_V_SCO, at(-76)), []);
  assert.deepEqual(due(HEA_V_SCO, at(-61)), ['xi']);
  assert.deepEqual(due(HEA_V_SCO, at(-60)), ['t60', 'xi']);
  assert.deepEqual(due(HEA_V_SCO, at(-30)), ['t30', 'xi']);
  assert.deepEqual(due(HEA_V_SCO, at(29)), ['xi']);
  assert.deepEqual(due(HEA_V_SCO, at(30)), []);
  const final = DATA.fixture.find(m => m.home === 'TBC');
  assert.deepEqual(due(final, Date.parse(final.start) - 45 * 60e3), []);
});

test('T-60 reminder goes to all, home and away topics once', async () => {
  const w = world();
  assert.deepEqual(await w.tick(-61), []);
  const sent = await w.tick(-60);
  assert.deepEqual(sent, ['40745 t60 scbbl-all', '40745 t60 scbbl-hea', '40745 t60 scbbl-sco']);
  const p = w.posts[0];
  assert.equal(p.title, 'HEA v SCO starts in 60 min');
  assert.match(p.message, /19:15 AEDT at /);
  assert.match(p.message, /Rain risk: Med \(40% peak/);
  assert.match(p.message, /XIs are named at the toss/);
  assert.equal(p.click, 'https://site.test/#/match/40745');
  assert.equal(p.auth, undefined);
  assert.deepEqual(await w.tick(-59), []);
  assert.equal(w.posts.length, 3);
});

test('reminder still goes out when the forecast fails, and lists unavailable players', async () => {
  const w = world({ forecast: false });
  DATA.availability = { ...DATA.availability, links: [...DATA.availability.links, { pid: DATA.squads.teams.HEA[0].pid, event: 'aus-nz-t4' }] };
  try {
    await w.tick(-60);
  } finally {
    DATA.availability = json('data/availability.json');
  }
  assert.doesNotMatch(w.posts[0].message, /Rain risk/);
  assert.match(w.posts[0].message, new RegExp(`Unavailable: ${DATA.squads.teams.HEA[0].n} \\(HEA\\): Australia v New Zealand, 4th Test`));
});

test('XI alert waits for the toss, then names the XIs and who missed out', async () => {
  const w = world();
  await w.tick(-60);
  assert.deepEqual(await w.tick(-30), ['40745 t30 scbbl-all', '40745 t30 scbbl-hea', '40745 t30 scbbl-sco']);
  assert.deepEqual(await w.tick(-25), []);
  w.card = CARD;
  const sent = await w.tick(-24);
  assert.deepEqual(sent, ['40745 xi scbbl-all', '40745 xi scbbl-hea', '40745 xi scbbl-sco']);
  const p = w.posts.at(-1);
  assert.equal(p.title, 'HEA v SCO: XIs named');
  const [hea, sco, toss] = p.message.split('\n\n');
  assert.match(hea, /^HEA: .*Jack Wildermuth/);
  assert.match(sco, /^SCO: .*Cooper Connolly/);
  assert.equal(hea.split('\n')[0].split(', ').length, 11);
  assert.match(hea, /\nLeft out: .*Tom Curran/);
  assert.equal(toss, 'Brisbane Heat won the toss and elected to bowl.');
  assert.deepEqual(await w.tick(0), []);
});

test('a reminder after the XI is out drops the toss line', async () => {
  const w = world({ card: CARD });
  await w.tick(-60);
  assert.equal(w.posts[0].title, 'HEA v SCO: XIs named');
  assert.doesNotMatch(w.posts.find(p => p.title.includes('60 min')).message, /named at the toss/);
});

test('a failed topic is retried alone next minute', async () => {
  const w = world({ failTopic: 'scbbl-hea' });
  assert.deepEqual(await w.tick(-60), ['40745 t60 scbbl-all', '40745 t60 scbbl-sco']);
  w.failTopic = null;
  assert.deepEqual(await w.tick(-59), ['40745 t60 scbbl-hea']);
});

test('a missed T-60 window is not sent late', async () => {
  const w = world();
  assert.deepEqual(await w.tick(-10), ['40745 t30 scbbl-all', '40745 t30 scbbl-hea', '40745 t30 scbbl-sco']);
});

test('quiet minutes touch no KV and NTFY_TOKEN is sent as Bearer', async () => {
  const w = world();
  let reads = 0;
  const get = w.env.SENT.get;
  w.env.SENT.get = k => { reads += 1; return get(k); };
  await run(w.env, Date.parse('2026-11-05T00:00:00Z'), w.fetch);
  assert.equal(reads, 0);
  w.env.NTFY_TOKEN = 'tk_abc';
  await w.tick(-60);
  assert.equal(w.posts[0].auth, 'Bearer tk_abc');
});
