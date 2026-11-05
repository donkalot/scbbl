import L from '../../logic.js';

const CA = 'https://apiv2.cricket.com.au/web/views/scorecard?jsconfig=eccn%3Atrue&format=json&fixtureId=';
const FORECAST = 'https://api.open-meteo.com/v1/forecast?hourly=precipitation_probability,precipitation&timezone=GMT&forecast_days=16';
const MIN = 60e3;
// Minutes relative to the scheduled start. A missed window is skipped, never caught up late.
export const WINDOWS = { t60: [-60, -30], xi: [-75, 30] };
const SITE_TTL = 10 * MIN;
const FETCH_MS = 8000;

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

export const topics = (m, prefix) => [`${prefix}-all`, `${prefix}-${m.home.toLowerCase()}`, `${prefix}-${m.away.toLowerCase()}`];

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
      if (ev) out.push(`${p.n} (${t}): ${ev.name}`);
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
  return { title: `${m.home} v ${m.away} starts in ${mins} min`, message: lines.join('\n'), tags: ['cricket_game'] };
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
  return { title: `${m.home} v ${m.away}: XIs named`, message: parts.join('\n\n'), tags: ['clipboard'] };
}

async function publish(env, fetchFn, topic, msg, click) {
  const headers = { 'content-type': 'application/json' };
  if (env.NTFY_TOKEN) headers.authorization = `Bearer ${env.NTFY_TOKEN}`;
  const r = await fetchFn(`${env.NTFY}/`, { method: 'POST', headers, body: JSON.stringify({ topic, ...msg, click }) });
  return r.ok;
}

async function tickMatch(m, kinds, env, data, fetchFn) {
  const key = `m:${m.id}`;
  const done = new Set(JSON.parse((await env.SENT.get(key)) || '[]'));
  const tops = topics(m, env.TOPIC_PREFIX);
  const click = `${env.SITE}/#/match/${m.id}`;
  const todo = kind => tops.filter(t => !done.has(`${kind}:${t}`));

  let xi = null;
  if (kinds.includes('xi') && todo('xi').length) {
    const r = await fetchFn(CA + m.id).catch(() => null);
    const card = r && r.ok ? await r.json().catch(() => null) : null;
    if (card && (card.players || []).length) xi = xiMessage(m, card, data);
  }
  const msgs = [];
  if (xi) msgs.push(['xi', xi]);
  if (kinds.includes('t60') && todo('t60').length) {
    const xiSent = xi || tops.some(t => done.has(`xi:${t}`));
    msgs.push(['t60', await reminder(m, 60, data, fetchFn, xiSent)]);
  }
  const jobs = msgs.flatMap(([kind, msg]) => todo(kind).map(t => ({ kind, t, msg })));
  const ok = await Promise.all(jobs.map(j => publish(env, fetchFn, j.t, j.msg, click).catch(() => false)));
  const sent = jobs.filter((_, i) => ok[i]);
  for (const j of sent) done.add(`${j.kind}:${j.t}`);
  if (sent.length) await env.SENT.put(key, JSON.stringify([...done]), { expirationTtl: 3 * 86400 });
  return sent.map(j => `${m.id} ${j.kind} ${j.t}`);
}

// One cron tick. Returns what was sent, for logs and tests.
export async function run(env, now, fetchFn) {
  // Ticks are a minute apart; timeouts keep one tick from overlapping the next and sending twice.
  const timed = (url, opts = {}) => fetchFn(url, { ...opts, signal: AbortSignal.timeout(FETCH_MS) });
  const data = await siteData(env, now, timed);
  const live = data.fixture.map(m => [m, due(m, now)]).filter(([, k]) => k.length);
  const sent = await Promise.all(live.map(([m, kinds]) => tickMatch(m, kinds, env, data, timed)));
  return sent.flat();
}
