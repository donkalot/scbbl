import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { run, due, resetCache, PUSH_BUDGET } from '../src/notify.js';
import { parse, subId, PREFIX } from '../src/subs.js';
import { browser, decrypt, checkVapid, memoryKV, vapidEnv } from './pushkit.js';

const root = new URL('../../', import.meta.url);
const json = p => JSON.parse(readFileSync(new URL(p, root), 'utf8'));
const DATA = Object.fromEntries(['fixture', 'squads', 'idmap', 'availability'].map(n => [n, json(`data/${n}.json`)]));
const CARD = json('tests/fixtures/ca_scorecard_23768.json');
const EMPTY = { players: [], fixture: { innings: [] } };
const HEA_V_SCO = DATA.fixture.find(m => m.id === 40745);
const START = Date.parse(HEA_V_SCO.start);
const at = mins => START + mins * 60e3;
const VAPID = await vapidEnv();
const FCM = 'https://fcm.googleapis.com/fcm/send/';

// Followers by name: each is a browser subscribed to the listed teams.
async function world({ card = EMPTY, forecast = true, follow = { all: ['all'], hea: ['HEA'], sco: ['SCO'], six: ['SIX'] } } = {}) {
  const kv = memoryKV();
  const browsers = {};
  for (const [name, teams] of Object.entries(follow)) {
    const b = await browser(FCM + name);
    browsers[FCM + name] = { name, ...b };
    await kv.put(PREFIX + await subId(b.sub.endpoint), '', { metadata: parse({ subscription: b.sub, teams }) });
  }
  kv.ops.put = 0;
  const w = {
    card, kv, pushes: [], status: {}, now: 0,
    env: { SITE: 'https://site.test', ...VAPID, SENT: kv },
    async fetch(url, opts = {}) {
      const u = String(url);
      const ok = body => ({ ok: true, status: 200, json: async () => body });
      if (u.startsWith('https://site.test/data/')) return ok(DATA[u.split('/').pop().replace('.json', '')]);
      if (u.startsWith('https://apiv2.cricket.com.au/')) return ok(w.card);
      if (u.startsWith('https://api.open-meteo.com/')) {
        if (!forecast) return { ok: false, status: 500 };
        const time = [], p = [], mm = [];
        for (let h = Math.floor(START / 3600e3) * 3600e3 - 6 * 3600e3; h < START + 12 * 3600e3; h += 3600e3) {
          time.push(new Date(h).toISOString().slice(0, 16)); p.push(40); mm.push(0.2);
        }
        return ok({ hourly: { time, precipitation_probability: p, precipitation: mm } });
      }
      if (browsers[u]) {
        const b = browsers[u];
        const status = w.status[b.name] ?? 201;
        if (status === 0) throw new Error('network down');
        await checkVapid(opts.headers.authorization, u, w.now);
        w.pushes.push({ to: b.name, status, headers: opts.headers, msg: await decrypt(opts.body, b) });
        return { ok: status < 300, status };
      }
      throw new Error('unexpected fetch ' + u);
    },
    async tick(mins) {
      w.now = at(mins);
      return (await run(w.env, w.now, w.fetch)).map(l => l.split(' ').at(-1));
    },
    to: () => w.pushes.filter(p => p.status < 300).map(p => p.to).sort(),
  };
  return w;
}

test.beforeEach(resetCache);

test('windows open at T-60 and T-75 for the XI, there is no T-30, and finals with TBC teams never fire', () => {
  assert.deepEqual(due(HEA_V_SCO, at(-76)), []);
  assert.deepEqual(due(HEA_V_SCO, at(-61)), ['xi']);
  assert.deepEqual(due(HEA_V_SCO, at(-60)), ['t60', 'xi']);
  assert.deepEqual(due(HEA_V_SCO, at(-31)), ['t60', 'xi']);
  assert.deepEqual(due(HEA_V_SCO, at(-30)), ['xi']);
  assert.deepEqual(due(HEA_V_SCO, at(29)), ['xi']);
  assert.deepEqual(due(HEA_V_SCO, at(30)), []);
  const final = DATA.fixture.find(m => m.home === 'TBC');
  assert.deepEqual(due(final, Date.parse(final.start) - 45 * 60e3), []);
});

test('T-60 reminder is pushed, encrypted and VAPID-signed, once to each follower of either team', async () => {
  const w = await world();
  assert.deepEqual(await w.tick(-61), []);
  assert.deepEqual(await w.tick(-60), ['201', '201', '201']);
  assert.deepEqual(w.to(), ['all', 'hea', 'sco']);
  const { msg, headers } = w.pushes[0];
  assert.equal(msg.title, 'HEA v SCO starts in 60 min');
  assert.match(msg.body, /19:15 AEDT at /);
  assert.match(msg.body, /Rain risk: Med \(40% peak/);
  assert.match(msg.body, /XIs are named at the toss/);
  assert.equal(msg.url, '#/match/40745');
  assert.equal(msg.tag, '40745-t60');
  assert.equal(headers['content-encoding'], 'aes128gcm');
  assert.equal(headers.ttl, '1800');
  assert.equal(headers.topic, 'm40745t60');
  assert.equal(headers.urgency, 'high');
  assert.deepEqual(await w.tick(-59), []);
  assert.equal(w.pushes.length, 3);
});

test('reminder still goes out when the forecast fails, and lists unavailable players', async () => {
  const w = await world({ forecast: false, follow: { all: ['all'] } });
  DATA.availability = { ...DATA.availability, links: [...DATA.availability.links, { pid: DATA.squads.teams.HEA[0].pid, event: 'aus-nz-t4' }] };
  try {
    await w.tick(-60);
  } finally {
    DATA.availability = json('data/availability.json');
  }
  const body = w.pushes[0].msg.body;
  assert.doesNotMatch(body, /Rain risk/);
  assert.match(body, new RegExp(`Unavailable: ${DATA.squads.teams.HEA[0].n} \\(HEA\\): Australia v New Zealand, 4th Test`));
});

test('XI alert waits for the toss, then names the XIs and who missed out', async () => {
  const w = await world();
  await w.tick(-60);
  assert.deepEqual(await w.tick(-30), []);
  w.card = CARD;
  assert.equal((await w.tick(-24)).length, 3);
  const p = w.pushes.at(-1);
  assert.equal(p.msg.title, 'HEA v SCO: XIs named');
  assert.equal(p.headers.ttl, String(3 * 3600));
  const [hea, sco, toss] = p.msg.body.split('\n\n');
  assert.match(hea, /^HEA: .*Jack Wildermuth/);
  assert.match(sco, /^SCO: .*Cooper Connolly/);
  assert.equal(hea.split('\n')[0].split(', ').length, 11);
  assert.match(hea, /\nLeft out: .*Tom Curran/);
  assert.equal(toss, 'Brisbane Heat won the toss and elected to bowl.');
  assert.deepEqual(await w.tick(0), []);
});

test('a reminder after the XI is out drops the toss line', async () => {
  const w = await world({ card: CARD, follow: { all: ['all'] } });
  await w.tick(-60);
  assert.equal(w.pushes[0].msg.title, 'HEA v SCO: XIs named');
  assert.doesNotMatch(w.pushes[1].msg.body, /named at the toss/);
});

test('busy or unreachable push services are retried alone; gone subscriptions are deleted; rejected ones are dropped', async () => {
  const w = await world({ follow: { busy: ['all'], down: ['all'], gone: ['HEA'], bad: ['SCO'], fine: ['SCO'] } });
  Object.assign(w.status, { busy: 503, down: 0, gone: 410, bad: 400 });
  assert.deepEqual((await w.tick(-60)).sort(), ['0', '201', '400', '410', '503']);
  assert.equal([...w.kv.m.keys()].filter(k => k.startsWith(PREFIX)).length, 4);
  w.status = {};
  const before = w.pushes.length;
  assert.deepEqual(await w.tick(-59), ['201', '201']);
  assert.deepEqual(w.pushes.slice(before).map(p => p.to).sort(), ['busy', 'down']);
  assert.deepEqual(await w.tick(-58), []);
});

test('a missed T-60 window is not sent late', async () => {
  const w = await world();
  assert.deepEqual(await w.tick(-30), []);
  assert.equal(w.pushes.length, 0);
});

test('quiet minutes touch no KV, and the subscriber list is only read once a message is ready', async () => {
  const w = await world();
  w.now = Date.parse('2026-11-05T00:00:00Z');
  await run(w.env, w.now, w.fetch);
  assert.deepEqual(w.kv.ops, { get: 0, list: 0, put: 0, delete: 0 });
  await w.tick(-70);
  await w.tick(-65);
  assert.equal(w.kv.ops.list, 0);
  assert.equal(w.kv.ops.put, 0);
});

test('a batch is claimed before it is sent, so a failed write loses alerts but never repeats them', async () => {
  const w = await world({ follow: { all: ['all'] } });
  const put = w.kv.put;
  let puts = 0;
  w.kv.put = async (...a) => { if (++puts === 2) throw new Error('kv down'); return put(...a); };
  await assert.rejects(w.tick(-60), /kv down/);
  assert.equal(w.pushes.length, 1);
  w.kv.put = put;
  assert.deepEqual(await w.tick(-59), []);
  assert.equal(w.pushes.length, 1);

  const v = await world({ follow: { all: ['all'] } });
  v.kv.put = async () => { throw new Error('kv down'); };
  await assert.rejects(v.tick(-60), /kv down/);
  assert.equal(v.pushes.length, 0);
});

test('pushes over the per-tick budget roll over to the next minute', async () => {
  const follow = Object.fromEntries(Array.from({ length: PUSH_BUDGET + 5 }, (_, i) => [`f${i}`, ['all']]));
  const w = await world({ follow });
  assert.equal((await w.tick(-60)).length, PUSH_BUDGET);
  assert.equal((await w.tick(-59)).length, 5);
  assert.equal(new Set(w.to()).size, PUSH_BUDGET + 5);
  assert.deepEqual(await w.tick(-58), []);
});
