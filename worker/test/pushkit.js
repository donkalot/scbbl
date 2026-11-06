// Test side of Web Push: browser-style subscriptions, payload decryption and VAPID checks.
import { b64u, unb64u, concat, hkdf } from '../src/webpush.js';

const subtle = crypto.subtle;
const te = new TextEncoder();
const P256 = { name: 'ECDH', namedCurve: 'P-256' };

export async function vapidEnv() {
  const kp = await subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  return { VAPID_PRIVATE: JSON.stringify(await subtle.exportKey('jwk', kp.privateKey)), VAPID_SUBJECT: 'https://site.test/' };
}

export async function browser(endpoint) {
  const kp = await subtle.generateKey(P256, true, ['deriveBits']);
  const pub = new Uint8Array(await subtle.exportKey('raw', kp.publicKey));
  const auth = crypto.getRandomValues(new Uint8Array(16));
  return { sub: { endpoint, keys: { p256dh: b64u(pub), auth: b64u(auth) } }, priv: kp.privateKey, pub, auth };
}

export async function decrypt(body, b) {
  body = new Uint8Array(body);
  const salt = body.slice(0, 16);
  const rs = new DataView(body.buffer, body.byteOffset).getUint32(16);
  const idlen = body[20];
  const asPub = body.slice(21, 21 + idlen);
  const asKey = await subtle.importKey('raw', asPub, P256, false, []);
  const shared = new Uint8Array(await subtle.deriveBits({ name: 'ECDH', public: asKey }, b.priv, 256));
  const ikm = await hkdf(b.auth, shared, concat(te.encode('WebPush: info\0'), b.pub, asPub), 32);
  const cek = await hkdf(salt, ikm, te.encode('Content-Encoding: aes128gcm\0'), 16);
  const iv = await hkdf(salt, ikm, te.encode('Content-Encoding: nonce\0'), 12);
  const key = await subtle.importKey('raw', cek, 'AES-GCM', false, ['decrypt']);
  const pt = new Uint8Array(await subtle.decrypt({ name: 'AES-GCM', iv }, key, body.slice(21 + idlen)));
  let end = pt.length - 1;
  while (pt[end] === 0) end -= 1;
  if (pt[end] !== 2 || rs !== 4096) throw new Error('bad record');
  return JSON.parse(new TextDecoder().decode(pt.slice(0, end)));
}

// Checks the VAPID header the way a push service does; returns the JWT claims and the key.
export async function checkVapid(header, endpoint, now) {
  const m = /^vapid t=([\w-]+)\.([\w-]+)\.([\w-]+), k=([\w-]+)$/.exec(header);
  if (!m) throw new Error('bad vapid header ' + header);
  const [, h, c, s, k] = m;
  const key = await subtle.importKey('raw', unb64u(k), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  const ok = await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, unb64u(s), te.encode(`${h}.${c}`));
  if (!ok) throw new Error('bad vapid signature');
  const head = JSON.parse(new TextDecoder().decode(unb64u(h)));
  const claims = JSON.parse(new TextDecoder().decode(unb64u(c)));
  if (head.alg !== 'ES256') throw new Error('bad alg');
  if (claims.aud !== new URL(endpoint).origin) throw new Error('bad aud');
  if (claims.exp * 1000 <= now || claims.exp * 1000 > now + 24 * 3600e3) throw new Error('bad exp');
  return { claims, k };
}

// Workers KV with metadata and prefix listing, in memory.
export function memoryKV() {
  const m = new Map();
  const kv = {
    m,
    ops: { get: 0, list: 0, put: 0, delete: 0 },
    async get(k) { kv.ops.get += 1; return m.has(k) ? m.get(k).v : null; },
    async getWithMetadata(k) { kv.ops.get += 1; const e = m.get(k); return { value: e ? e.v : null, metadata: e ? e.md ?? null : null }; },
    async put(k, v, o = {}) { kv.ops.put += 1; m.set(k, { v, md: o.metadata }); },
    async delete(k) { kv.ops.delete += 1; m.delete(k); },
    async list({ prefix = '', cursor } = {}) {
      kv.ops.list += 1;
      const keys = [...m.keys()].filter(k => k.startsWith(prefix)).sort();
      const from = cursor ? Number(cursor) : 0;
      const page = keys.slice(from, from + 2);
      const done = from + 2 >= keys.length;
      return { keys: page.map(name => ({ name, metadata: m.get(name).md })), list_complete: done, cursor: done ? undefined : String(from + 2) };
    },
  };
  return kv;
}
