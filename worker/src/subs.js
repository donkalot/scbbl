import L from '../../logic.js';
import { b64u, unb64u, push, vapid } from './webpush.js';

// Chrome/Android (FCM), Firefox, Edge (WNS) and Safari/iOS. Anything else is refused. `token` picks out what
// identifies the subscription, so one subscription can't be stored twice under spellings the service treats alike.
const SERVICES = [
  { name: 'fcm', host: /^fcm\.googleapis\.com$/, url: /^\/(?:fcm\/send|wp)\/([\w:-]+)$/ },
  { name: 'moz', host: /^updates\.push\.services\.mozilla\.com$/, url: /^\/wpush\/v[12]\/([\w=-]+)$/ },
  { name: 'wns', host: /^[\w-]+\.notify\.windows\.com$/, url: /^\/w\/\?token=([\w%.-]+)$/, decode: true },
  { name: 'apple', host: /^([\w-]+\.)*push\.apple\.com$/, url: /^\/([\w=-]+)$/ },
];
const MAX_BODY = 4096;
const MAX_ENDPOINT = 600;
export const PREFIX = 'sub:';

// The KV key suffix for an endpoint, or null if it isn't an endpoint we accept.
export async function subId(endpoint) {
  const t = token(endpoint);
  if (!t) return null;
  const h = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t)));
  return b64u(h).slice(0, 22);
}

function token(e) {
  let u;
  try { u = new URL(e); } catch { return null; }
  // Exact spelling only: no default port, userinfo, fragment, case or dot-segment variants.
  if (u.href !== e || u.protocol !== 'https:' || u.port || u.username || u.password || u.hash) return null;
  const svc = SERVICES.find(x => x.host.test(u.hostname));
  const m = svc && svc.url.exec(u.pathname + u.search);
  if (!m) return null;
  try { return `${svc.name}:${svc.decode ? decodeURIComponent(m[1]) : m[1]}`; } catch { return null; }
}

const bytes = s => { try { return typeof s === 'string' && s.length < 200 ? unb64u(s) : null; } catch { return null; } };

// Returns the KV metadata for a subscription, or an error string.
export function parse(body) {
  const s = body && body.subscription;
  const e = s && s.endpoint;
  if (typeof e !== 'string' || e.length > MAX_ENDPOINT) return 'bad endpoint';
  if (!token(e)) return 'unsupported push service';
  const pb = bytes(s.keys && s.keys.p256dh), ab = bytes(s.keys && s.keys.auth);
  if (!pb || pb.length !== 65 || pb[0] !== 4 || !ab || ab.length !== 16) return 'bad keys';
  if (!Array.isArray(body.teams)) return 'bad teams';
  const t = [...new Set(body.teams)];
  if (!t.length || !t.every(x => x === 'all' || L.TEAMS.includes(x))) return 'bad teams';
  return { e, p: b64u(pb), a: b64u(ab), t: t.includes('all') ? ['all'] : t };
}

export const asSub = md => ({ endpoint: md.e, keys: { p256dh: md.p, auth: md.a } });

const label = t => (t[0] === 'all' ? 'every match' : t.join(', '));

async function subscribe(body, env, fetchFn, now) {
  const md = parse(body);
  if (typeof md === 'string') return [400, { error: md }];
  const key = PREFIX + await subId(md.e);
  const old = (await env.SENT.getWithMetadata(key)).metadata;
  if (old && old.p === md.p && old.a === md.a) {
    if (old.t.join() !== md.t.join()) await env.SENT.put(key, '', { metadata: { ...old, t: md.t } });
    return [200, { teams: md.t }];
  }
  // A browser keeps its keys for the life of an endpoint, so different keys mean someone else is replaying it.
  if (old) return [409, { error: 'already subscribed' }];
  // A new endpoint must take a push before it is stored, so junk never reaches the list the cron reads.
  const status = await push(asSub(md), {
    title: 'SC BBL match alerts on',
    body: `You'll get the hour-before reminder and the XIs at the toss for ${label(md.t)}.`,
    tag: 'scbbl-subscribed',
    url: '#/matches',
  }, env, fetchFn, { ttl: 600, now });
  if (status < 200 || status > 299) return [400, { error: `push service refused (${status})` }];
  await env.SENT.put(key, '', { metadata: md });
  return [201, { teams: md.t }];
}

// Needs the subscription's auth secret as well as its endpoint, and only spends a KV delete on a real record.
async function unsubscribe(body, env) {
  const id = typeof (body && body.endpoint) === 'string' && await subId(body.endpoint);
  if (!id) return [400, { error: 'bad endpoint' }];
  const key = PREFIX + id;
  const old = (await env.SENT.getWithMetadata(key)).metadata;
  const ab = bytes(body.auth);
  if (!old || !ab || old.a !== b64u(ab)) return [404, { error: 'not subscribed' }];
  await env.SENT.delete(key);
  return [200, {}];
}

export async function handle(req, env, fetchFn = fetch, now = Date.now()) {
  const origin = req.headers.get('origin');
  const ok = (env.ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean).includes(origin);
  const cors = ok ? { 'access-control-allow-origin': origin, 'access-control-allow-methods': 'GET, POST', 'access-control-allow-headers': 'content-type', vary: 'origin' } : { vary: 'origin' };
  const reply = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { ...cors, 'content-type': 'application/json' } });
  const path = new URL(req.url).pathname;

  if (req.method === 'OPTIONS') return new Response(null, { status: ok ? 204 : 403, headers: cors });
  if (req.method === 'GET' && path === '/vapid') return reply(200, { key: (await vapid(env)).pub });
  if (req.method === 'POST' && (path === '/subscribe' || path === '/unsubscribe')) {
    if (!ok) return reply(403, { error: 'origin not allowed' });
    if (Number(req.headers.get('content-length')) > MAX_BODY) return reply(413, { error: 'too large' });
    const text = await req.text();
    if (text.length > MAX_BODY) return reply(413, { error: 'too large' });
    let body;
    try { body = JSON.parse(text); } catch { return reply(400, { error: 'bad json' }); }
    const [status, out] = path === '/subscribe' ? await subscribe(body, env, fetchFn, now) : await unsubscribe(body, env);
    return reply(status, out);
  }
  return new Response('scbbl notifier. Turn on match alerts on the Matches page of https://donkalot.github.io/scbbl/\n', { status: path === '/' ? 200 : 404 });
}
