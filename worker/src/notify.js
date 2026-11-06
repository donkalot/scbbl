import L from '../../logic.js';
import { push, fit } from './webpush.js';
import { PREFIX, asSub } from './subs.js';

const CA = 'https://apiv2.cricket.com.au/web/views/scorecard?jsconfig=eccn%3Atrue&format=json&fixtureId=';
const FORECAST = 'https://api.open-meteo.com/v1/forecast?hourly=precipitation_probability,precipitation&timezone=GMT&forecast_days=16';
const MIN = 60e3;
// Minutes relative to the scheduled start. A missed window is skipped, never caught up late.
export const WINDOWS = { t60: [-60, -30], xi: [-75, 30] };
const SITE_TTL = 10 * MIN;
const FETCH_MS = 8000;
// Push fetches queue behind the 6-connection limit, so a short timer could abort one the service already took.
const PUSH_MS = 30000;
// Each push costs about 0.3 ms of CPU for its encryption, against the free plan's 10 ms a tick. Overflow goes next minute.
export const PUSH_BUDGET = 20;
// How long a push service holds an undelivered alert, in seconds.
const TTL = { t60: 1800, xi: 3 * 3600 };

let site = null;

async function siteData(env, now, fetchFn) {
  if (site && now - site.at < SITE_TTL && site.base === env.SITE) return site.data;
  const get = n => fetchFn(`${env.SITE}/data/${n}.json`).then(r => {
    if (!r.ok) throw new Error(`${n}.json ${r.status}`);
    return r.json();
  });
  const [fixture, squads, idmap, availability] = await Promise.all(['fixture', 'squads', 'idmap', 'availability'].map(get));
  site = { at: now, base: env.SITE, data: { fixture, squads, idmap, availability } };
  return site.data;
}

export function resetCache() { site = null; }

export function due(m, now) {
  if (m.home === 'TBC' || m.away === 'TBC') return [];
  const mins = (now - Date.parse(m.start)) / MIN;
  return Object.entries(WINDOWS).filter(([, [a, b]]) => mins >= a && mins < b).map(([k]) => k);
}

const aedt = iso => new Date(Date.parse(iso) + 11 * 3600e3).toISOString().slice(11, 16);

async function rain(m, fetchFn) {
  try {
    const r = await fetchFn(`${FORECAST}&latitude=${m.venue.lat}&longitude=${m.venue.lon}`);
    if (!r.ok) return null;
    const h = (await r.json()).hourly;
    const at = Object.fromEntries(h.time.map((t, i) => [t, { p: h.precipitation_probability[i], mm: h.precipitation[i] }]));
    const hours = L.windowHours(m.start, m.end).map(t => at[t]);
    if (hours.some(x => !x)) return null;
    return L.rainRisk(hours);
  } catch {
    return null;
  }
}

function unavailable(m, data) {
  const day = L.localDate(m.start);
  const out = [];
  for (const t of [m.home, m.away]) {
    for (const p of data.squads.teams[t] || []) {
      const ev = L.eventsFor(p.pid, data.availability).find(e => e.start <= day && day <= e.end);
      if (ev) out.push(`${p.n} (${t}): ${ev.name}${ev.likely ? ' (likely)' : ''}`);
    }
  }
  return out;
}

export async function reminder(m, mins, data, fetchFn, xiSent) {
  const lines = [`${aedt(m.start)} AEDT at ${m.venue.name}, ${m.venue.city}`];
  const r = await rain(m, fetchFn);
  if (r) lines.push(`Rain risk: ${r.level} (${r.maxP}% peak, ${r.mm.toFixed(1)} mm)`);
  const out = unavailable(m, data);
  if (out.length) lines.push(`Unavailable: ${out.join('; ')}`);
  if (!xiSent) lines.push('XIs are named at the toss.');
  return { title: `${m.home} v ${m.away} starts in ${mins} min`, body: lines.join('\n') };
}

export function xiMessage(m, card, data) {
  const lines = L.caLines(card);
  const fx = card.fixture || {};
  const parts = [];
  for (const code of [m.home, m.away]) {
    const teamId = code === m.home ? fx.homeTeamId : fx.awayTeamId;
    const xi = lines.filter(l => l.team === teamId);
    const squad = data.squads.teams[code] || [];
    const picked = new Set(xi.map(l => L.matchPid(l, data.idmap, squad)).filter(Boolean));
    const names = xi.map(l => l.name + (l.captain ? ' (c)' : '') + (l.keeper ? ' (wk)' : ''));
    const left = squad.filter(p => !picked.has(p.pid)).map(p => p.n);
    parts.push(`${code}: ${names.join(', ')}` + (left.length ? `\nLeft out: ${left.join(', ')}` : ''));
  }
  if (fx.tossResult) parts.push(fx.tossResult);
  return { title: `${m.home} v ${m.away}: XIs named`, body: parts.join('\n\n') };
}

async function subscribers(env) {
  const out = [];
  let cursor;
  do {
    const r = await env.SENT.list({ prefix: PREFIX, cursor });
    for (const k of r.keys) if (k.metadata) out.push({ id: k.name.slice(PREFIX.length), ...k.metadata });
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return out;
}

export const wants = (s, m) => s.t.includes('all') || s.t.includes(m.home) || s.t.includes(m.away);

// Push service replies: 2xx delivered, 404/410 the subscription is gone, other 4xx won't succeed on retry.
const retryable = status => status === 0 || status === 429 || status >= 500;

async function tickMatch(m, kinds, env, data, fetchFn, ctx) {
  const key = `m:${m.id}`;
  const done = new Set(JSON.parse((await env.SENT.get(key)) || '[]'));
  const open = kinds.filter(k => !done.has(`${k}:complete`));
  if (!open.length) return [];

  let xi = null;
  if (open.includes('xi')) {
    const r = await fetchFn(CA + m.id).catch(() => null);
    const card = r && r.ok ? await r.json().catch(() => null) : null;
    if (card && (card.players || []).length) xi = xiMessage(m, card, data);
  }
  const msgs = [];
  if (xi) msgs.push(['xi', xi]);
  if (open.includes('t60')) {
    const xiSent = xi || [...done].some(d => d.startsWith('xi:'));
    msgs.push(['t60', await reminder(m, 60, data, fetchFn, xiSent)]);
  }
  if (!msgs.length) return [];

  const subs = (await ctx.subs()).filter(s => wants(s, m));
  const plan = msgs.map(([kind, msg]) => {
    const todo = subs.filter(s => !done.has(`${kind}:${s.id}`) && !ctx.gone.has(s.id));
    const batch = todo.slice(0, Math.max(0, ctx.budget));
    ctx.budget -= batch.length;
    return { kind, msg, batch, more: todo.length > batch.length };
  });
  const save = () => env.SENT.put(key, JSON.stringify([...done]), { expirationTtl: 3 * 86400 });
  const before = done.size;
  // Claim the batch before sending, so a tick that dies or can't write afterwards never sends it twice.
  for (const { kind, batch } of plan) for (const s of batch) done.add(`${kind}:${s.id}`);
  if (done.size > before) await save();

  const log = [];
  let changed = false;
  for (const { kind, msg, batch, more } of plan) {
    const payload = fit({ ...msg, url: `#/match/${m.id}`, tag: `${m.id}-${kind}` });
    const statuses = await Promise.all(batch.map(s => push(asSub(s), payload, env, ctx.pushFetch, { ttl: TTL[kind], topic: `m${m.id}${kind}`, now: ctx.now })));
    let again = more;
    batch.forEach((s, i) => {
      const st = statuses[i];
      log.push(`${m.id} ${kind} ${s.id} ${st}`);
      if (st === 404 || st === 410) ctx.gone.add(s.id);
      else if (retryable(st)) { done.delete(`${kind}:${s.id}`); again = changed = true; }
    });
    if (!again) { done.add(`${kind}:complete`); changed = true; }
  }
  if (changed) await save();
  return log;
}

// One cron tick. Returns one line per push attempt, for logs and tests.
export async function run(env, now, fetchFn) {
  // Ticks are a minute apart; timeouts keep one tick from overlapping the next and sending twice.
  const timed = (url, opts = {}) => fetchFn(url, { ...opts, signal: AbortSignal.timeout(FETCH_MS) });
  const data = await siteData(env, now, timed);
  const live = data.fixture.map(m => [m, due(m, now)]).filter(([, k]) => k.length);
  let listed = null;
  const ctx = {
    now, budget: PUSH_BUDGET, gone: new Set(), subs: () => (listed ||= subscribers(env)),
    pushFetch: (url, opts) => fetchFn(url, { ...opts, signal: AbortSignal.timeout(PUSH_MS) }),
  };
  const sent = [];
  // In series, so the push budget is shared fairly and the subscriber list is read once.
  for (const [m, kinds] of live) sent.push(...await tickMatch(m, kinds, env, data, timed, ctx));
  await Promise.all([...ctx.gone].map(id => env.SENT.delete(PREFIX + id)));
  return sent;
}
