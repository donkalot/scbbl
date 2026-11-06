// Web Push with no dependencies: VAPID (RFC 8292) and aes128gcm payload encryption (RFC 8291), on WebCrypto.
const subtle = crypto.subtle;
const te = new TextEncoder();
const P256 = { name: 'ECDH', namedCurve: 'P-256' };
const RS = 4096;
// Push services must accept 4096-byte bodies: 86 header + plaintext + 1 delimiter + 16 tag.
export const MAX_PLAINTEXT = RS - 86 - 17;

export const b64u = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
export const unb64u = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));

export function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let i = 0;
  for (const p of parts) { out.set(p, i); i += p.length; }
  return out;
}

export async function hkdf(salt, ikm, info, len) {
  const k = await subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, k, len * 8));
}

// `sender` ({privateKey, publicKey}) and `salt` are only passed by tests; normally both are fresh per message.
export async function encrypt(plaintext, keys, { sender, salt } = {}) {
  if (plaintext.length > MAX_PLAINTEXT) throw new Error('payload too large');
  const ua = unb64u(keys.p256dh);
  const auth = unb64u(keys.auth);
  if (ua.length !== 65 || auth.length !== 16) throw new Error('bad subscription keys');
  const uaKey = await subtle.importKey('raw', ua, P256, false, []);
  const as = sender || await subtle.generateKey(P256, true, ['deriveBits']);
  const asPub = new Uint8Array(await subtle.exportKey('raw', as.publicKey));
  const shared = new Uint8Array(await subtle.deriveBits({ name: 'ECDH', public: uaKey }, as.privateKey, 256));
  const ikm = await hkdf(auth, shared, concat(te.encode('WebPush: info\0'), ua, asPub), 32);
  salt = salt || crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, te.encode('Content-Encoding: aes128gcm\0'), 16);
  const iv = await hkdf(salt, ikm, te.encode('Content-Encoding: nonce\0'), 12);
  const key = await subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const ct = new Uint8Array(await subtle.encrypt({ name: 'AES-GCM', iv }, key, concat(plaintext, [2])));
  const header = new Uint8Array(21 + asPub.length);
  header.set(salt);
  new DataView(header.buffer).setUint32(16, RS);
  header[20] = asPub.length;
  header.set(asPub, 21);
  return concat(header, ct);
}

const size = o => te.encode(JSON.stringify(o)).length;

// Shortens `body` so the payload fits in one push; anything else that overflows is left for encrypt() to refuse.
export function fit(payload) {
  if (size(payload) <= MAX_PLAINTEXT) return payload;
  const chars = [...(payload.body || '')];
  let lo = 0, hi = chars.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (size({ ...payload, body: chars.slice(0, mid).join('') + '…' }) <= MAX_PLAINTEXT) lo = mid; else hi = mid - 1;
  }
  return { ...payload, body: chars.slice(0, lo).join('') + '…' };
}

let cached = null;

// VAPID_PRIVATE is the JWK of an ECDSA P-256 key; the public key is derived from its x and y.
export async function vapid(env) {
  if (cached && cached.src === env.VAPID_PRIVATE) return cached;
  const { kty, crv, d, x, y } = JSON.parse(env.VAPID_PRIVATE);
  const key = await subtle.importKey('jwk', { kty, crv, d, x, y }, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  cached = { src: env.VAPID_PRIVATE, key, pub: b64u(concat([4], unb64u(x), unb64u(y))), jwts: new Map() };
  return cached;
}

async function authHeader(endpoint, v, subject, now) {
  const aud = new URL(endpoint).origin;
  const hit = v.jwts.get(aud);
  if (hit && hit.exp * 1000 - now > 3600e3) return hit.header;
  const exp = Math.floor(now / 1000) + 12 * 3600;
  const enc = o => b64u(te.encode(JSON.stringify(o)));
  const unsigned = `${enc({ typ: 'JWT', alg: 'ES256' })}.${enc({ aud, exp, sub: subject })}`;
  const sig = new Uint8Array(await subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, v.key, te.encode(unsigned)));
  const header = `vapid t=${unsigned}.${b64u(sig)}, k=${v.pub}`;
  v.jwts.set(aud, { exp, header });
  return header;
}

// Returns the push service's HTTP status, 0 if the request failed, or 400 if the subscription's key is unusable.
export async function push(sub, payload, env, fetchFn, { ttl, topic, now = Date.now() }) {
  const v = await vapid(env);
  let body;
  try {
    body = await encrypt(te.encode(JSON.stringify(payload)), sub.keys);
  } catch {
    return 400;
  }
  const headers = {
    authorization: await authHeader(sub.endpoint, v, env.VAPID_SUBJECT, now),
    'content-encoding': 'aes128gcm',
    'content-type': 'application/octet-stream',
    ttl: String(ttl),
    urgency: 'high',
  };
  if (topic) headers.topic = topic;
  try {
    return (await fetchFn(sub.endpoint, { method: 'POST', headers, body })).status;
  } catch {
    return 0;
  }
}
