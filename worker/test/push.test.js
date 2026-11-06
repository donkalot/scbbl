import test from 'node:test';
import assert from 'node:assert/strict';
import { encrypt, push, b64u, unb64u, vapid, fit, MAX_PLAINTEXT } from '../src/webpush.js';
import { handle, subId, PREFIX } from '../src/subs.js';
import { browser, decrypt, checkVapid, memoryKV, vapidEnv } from './pushkit.js';

const VAPID = await vapidEnv();
const SITE = 'https://donkalot.github.io';
const FCM = 'https://fcm.googleapis.com/fcm/send/abc';

test('encryption reproduces the RFC 8291 section 5 example byte for byte', async () => {
  const pub = unb64u('BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8');
  const P = { name: 'ECDH', namedCurve: 'P-256' };
  const jwk = { kty: 'EC', crv: 'P-256', d: 'yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw', x: b64u(pub.slice(1, 33)), y: b64u(pub.slice(33)) };
  const sender = { privateKey: await crypto.subtle.importKey('jwk', jwk, P, false, ['deriveBits']), publicKey: await crypto.subtle.importKey('raw', pub, P, true, []) };
  const keys = { p256dh: 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4', auth: 'BTBZMqHH6r4Tts7J_aSIgg' };
  const out = await encrypt(new TextEncoder().encode('When I grow up, I want to be a watermelon'), keys, { sender, salt: unb64u('DGv6ra1nlYgDCS1FRnbzlw') });
  assert.equal(b64u(out), 'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT'
    + 'pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN');
});

test('each message uses a fresh key and salt, and oversized payloads are refused', async () => {
  const b = await browser(FCM);
  const pt = new TextEncoder().encode('{"title":"x"}');
  const [a, c] = [await encrypt(pt, b.sub.keys), await encrypt(pt, b.sub.keys)];
  assert.notEqual(b64u(a.slice(0, 86)), b64u(c.slice(0, 86)));
  await assert.rejects(encrypt(new Uint8Array(4080), b.sub.keys), /too large/);
});

test('VAPID header verifies against the derived public key, and is reused per push service', async () => {
  const b = await browser(FCM);
  const seen = [];
  const fetchFn = async (url, opts) => { seen.push(opts.headers.authorization); return { status: 201 }; };
  const now = Date.parse('2026-12-12T07:00:00Z');
  assert.equal(await push(b.sub, { title: 'hi' }, VAPID, fetchFn, { ttl: 60, now }), 201);
  await push(b.sub, { title: 'hi' }, VAPID, fetchFn, { ttl: 60, now: now + 60e3 });
  const { claims, k } = await checkVapid(seen[0], FCM, now);
  assert.equal(k, (await vapid(VAPID)).pub);
  assert.equal(unb64u(k).length, 65);
  assert.equal(claims.sub, 'https://site.test/');
  assert.equal(claims.exp, now / 1000 + 12 * 3600);
  assert.equal(seen[1], seen[0]);
  const other = await browser('https://updates.push.services.mozilla.com/wpush/v2/xyz');
  await push(other.sub, { title: 'hi' }, VAPID, fetchFn, { ttl: 60, now });
  assert.equal((await checkVapid(seen[2], other.sub.endpoint, now)).claims.aud, 'https://updates.push.services.mozilla.com');
});

test('a network failure reports status 0, and a key off the P-256 curve reports 400 without sending', async () => {
  const b = await browser(FCM);
  assert.equal(await push(b.sub, {}, VAPID, async () => { throw new Error('down'); }, { ttl: 60 }), 0);
  const offCurve = b64u(new Uint8Array([4, ...new Uint8Array(63), 1, 1]));
  assert.equal(await push({ ...b.sub, keys: { ...b.sub.keys, p256dh: offCurve } }, {}, VAPID, async () => assert.fail('sent'), { ttl: 60 }), 400);
});

function api({ status = 201 } = {}) {
  const kv = memoryKV();
  const a = {
    kv, pushes: [], status,
    env: { ...VAPID, SENT: kv, ORIGINS: `${SITE}, http://localhost:8000` },
    fetch: async (url, opts) => { a.pushes.push({ url, opts }); return { status: a.status }; },
    call: (path, { method = 'POST', body, origin = SITE, raw } = {}) => handle(new Request('https://w.test' + path, {
      method, headers: origin ? { origin, 'content-type': 'application/json' } : {}, body: raw ?? (body && JSON.stringify(body)),
    }), a.env, a.fetch),
  };
  return a;
}

const stored = async (a, endpoint) => (await a.kv.getWithMetadata(PREFIX + await subId(endpoint))).metadata;

test('GET /vapid returns the public key with CORS for the site only', async () => {
  const a = api();
  const r = await a.call('/vapid', { method: 'GET' });
  assert.equal((await r.json()).key, (await vapid(VAPID)).pub);
  assert.equal(r.headers.get('access-control-allow-origin'), SITE);
  const pre = await a.call('/subscribe', { method: 'OPTIONS', origin: 'http://localhost:8000' });
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get('access-control-allow-origin'), 'http://localhost:8000');
  assert.equal((await a.call('/subscribe', { method: 'OPTIONS', origin: 'https://evil.test' })).status, 403);
  assert.equal((await a.call('/nope', { method: 'GET' })).status, 404);
});

test('a new subscription gets a confirmation push before it is stored', async () => {
  const a = api();
  const b = await browser(FCM);
  const r = await a.call('/subscribe', { body: { subscription: b.sub, teams: ['HEA', 'SCO', 'HEA'] } });
  assert.equal(r.status, 201);
  assert.deepEqual(await r.json(), { teams: ['HEA', 'SCO'] });
  assert.equal(a.pushes.length, 1);
  const msg = await decrypt(a.pushes[0].opts.body, b);
  assert.equal(msg.title, 'SC BBL match alerts on');
  assert.match(msg.body, /for HEA, SCO\./);
  assert.deepEqual(await stored(a, FCM), { e: FCM, p: b.sub.keys.p256dh, a: b.sub.keys.auth, t: ['HEA', 'SCO'] });
});

test('re-subscribing changes teams without another push, and unchanged teams write nothing', async () => {
  const a = api();
  const b = await browser(FCM);
  await a.call('/subscribe', { body: { subscription: b.sub, teams: ['HEA'] } });
  const r = await a.call('/subscribe', { body: { subscription: b.sub, teams: ['SIX', 'all'] } });
  assert.equal(r.status, 200);
  assert.deepEqual((await stored(a, FCM)).t, ['all']);
  const puts = a.kv.ops.put;
  await a.call('/subscribe', { body: { subscription: b.sub, teams: ['all'] } });
  assert.equal(a.kv.ops.put, puts);
  assert.equal(a.pushes.length, 1);
});

test('subscriptions the push service refuses are not stored', async () => {
  const a = api({ status: 404 });
  const b = await browser(FCM);
  const r = await a.call('/subscribe', { body: { subscription: b.sub, teams: ['all'] } });
  assert.equal(r.status, 400);
  assert.match((await r.json()).error, /refused \(404\)/);
  assert.equal(await stored(a, FCM), null);
});

test('bad input is rejected before any push or write', async () => {
  const a = api();
  const b = await browser(FCM);
  const bad = [
    [{ subscription: { ...b.sub, endpoint: 'https://evil.test/push' }, teams: ['all'] }, 'unsupported push service'],
    [{ subscription: { ...b.sub, endpoint: 'http://fcm.googleapis.com/x' }, teams: ['all'] }, 'unsupported push service'],
    [{ subscription: { ...b.sub, endpoint: FCM + 'x'.repeat(600) }, teams: ['all'] }, 'bad endpoint'],
    [{ subscription: { ...b.sub, keys: { ...b.sub.keys, auth: 'AAAA' } }, teams: ['all'] }, 'bad keys'],
    [{ subscription: { ...b.sub, keys: { p256dh: b64u(new Uint8Array(65)), auth: b.sub.keys.auth } }, teams: ['all'] }, 'bad keys'],
    [{ subscription: b.sub, teams: [] }, 'bad teams'],
    [{ subscription: b.sub, teams: ['XYZ'] }, 'bad teams'],
    [{ subscription: b.sub, teams: 'HEA' }, 'bad teams'],
    [{}, 'bad endpoint'],
  ];
  for (const [body, error] of bad) {
    const r = await a.call('/subscribe', { body });
    assert.equal(r.status, 400, error);
    assert.equal((await r.json()).error, error);
  }
  assert.equal((await a.call('/subscribe', { raw: '{nope' })).status, 400);
  assert.equal((await a.call('/subscribe', { raw: ' '.repeat(5000) })).status, 413);
  assert.equal((await a.call('/subscribe', { body: { subscription: b.sub, teams: ['all'] }, origin: 'https://evil.test' })).status, 403);
  assert.equal((await a.call('/subscribe', { body: { subscription: b.sub, teams: ['all'] }, origin: null })).status, 403);
  assert.equal(a.pushes.length, 0);
  assert.equal(a.kv.ops.put, 0);
});

test('Edge, Firefox and Safari endpoints are accepted; unsubscribe deletes', async () => {
  const a = api();
  for (const e of ['https://wns2-sy3p.notify.windows.com/w/?token=abc', 'https://updates.push.services.mozilla.com/wpush/v2/abc', 'https://web.push.apple.com/abc']) {
    const b = await browser(e);
    assert.equal((await a.call('/subscribe', { body: { subscription: b.sub, teams: ['all'] } })).status, 201, e);
  }
  const apple = 'https://web.push.apple.com/abc';
  const { a: auth } = await stored(a, apple);
  assert.equal((await a.call('/unsubscribe', { body: { endpoint: apple, auth } })).status, 200);
  assert.equal(await stored(a, apple), null);
  assert.ok(await stored(a, 'https://updates.push.services.mozilla.com/wpush/v2/abc'));
});

test('unsubscribe needs the auth secret and spends no delete on a missing record', async () => {
  const a = api();
  const b = await browser(FCM);
  await a.call('/subscribe', { body: { subscription: b.sub, teams: ['all'] } });
  const other = await browser(FCM);
  for (const body of [{ endpoint: FCM }, { endpoint: FCM, auth: other.sub.keys.auth }, { endpoint: FCM, auth: 'nope!' }, { endpoint: FCM + 'z', auth: b.sub.keys.auth }]) {
    assert.equal((await a.call('/unsubscribe', { body })).status, 404, JSON.stringify(body));
  }
  assert.equal((await a.call('/unsubscribe', { body: { endpoint: 'https://evil.test/x', auth: b.sub.keys.auth } })).status, 400);
  assert.equal(a.kv.ops.delete, 0);
  assert.ok(await stored(a, FCM));
  const padded = btoa(String.fromCharCode(...unb64u(b.sub.keys.auth)));
  assert.equal((await a.call('/unsubscribe', { body: { endpoint: FCM, auth: padded } })).status, 200);
  assert.equal(await stored(a, FCM), null);
});

test('one subscription can only be stored once, whatever the spelling of its endpoint or keys', async () => {
  for (const e of [FCM + '#1', FCM + '?a', 'https://fcm.googleapis.com:443/fcm/send/abc', 'https://fcm.googleapis.com:8443/fcm/send/abc',
    'https://u@fcm.googleapis.com/fcm/send/abc', 'https://FCM.googleapis.com/fcm/send/abc', 'https://fcm.googleapis.com/fcm/./send/abc']) {
    assert.equal(await subId(e), null, e);
  }
  assert.equal(await subId('https://wns2-sy3p.notify.windows.com/w/?token=a%2Fb'), await subId('https://db5p.notify.windows.com/w/?token=a%2fb'));
  assert.equal(await subId('https://fcm.googleapis.com/wp/abc'), await subId(FCM));

  const a = api();
  const b = await browser(FCM);
  const std = s => btoa(String.fromCharCode(...unb64u(s)));
  const r = await a.call('/subscribe', { body: { subscription: { endpoint: FCM, keys: { p256dh: std(b.sub.keys.p256dh), auth: std(b.sub.keys.auth) } }, teams: ['all'] } });
  assert.equal(r.status, 201);
  assert.deepEqual(await stored(a, FCM), { e: FCM, p: b.sub.keys.p256dh, a: b.sub.keys.auth, t: ['all'] });

  const thief = await browser('https://fcm.googleapis.com/wp/abc');
  const [puts, pushes] = [a.kv.ops.put, a.pushes.length];
  const t = await a.call('/subscribe', { body: { subscription: thief.sub, teams: ['HEA'] } });
  assert.equal(t.status, 409);
  assert.equal(a.kv.ops.put, puts);
  assert.equal(a.pushes.length, pushes);
  assert.deepEqual((await stored(a, FCM)).t, ['all']);
});

test('an oversized content-length is refused before the body is read', async () => {
  const a = api();
  const req = new Request('https://w.test/subscribe', { method: 'POST', headers: { origin: SITE, 'content-type': 'application/json', 'content-length': '999999' }, body: '{}' });
  req.text = () => assert.fail('body read');
  assert.equal((await handle(req, a.env, a.fetch)).status, 413);
});

test('fit shortens a long body so the push still encrypts within one record', async () => {
  const b = await browser(FCM);
  const short = { title: 'x', body: 'hi' };
  assert.equal(fit(short), short);
  const long = { title: 'XI announced', body: 'Ö'.repeat(5000), url: '#/live/1' };
  await assert.rejects(encrypt(new TextEncoder().encode(JSON.stringify(long)), b.sub.keys), /too large/);
  const f = fit(long);
  const pt = new TextEncoder().encode(JSON.stringify(f));
  assert.ok(pt.length <= MAX_PLAINTEXT && pt.length > MAX_PLAINTEXT - 4);
  assert.ok(f.body.endsWith('…') && f.title === long.title && f.url === long.url);
  assert.ok((await encrypt(pt, b.sub.keys)).length <= 4096);
});
