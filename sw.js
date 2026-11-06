const CACHE = 'scbbl-v15';
const APP_SHELL = ['./', './index.html', './logic.js', './app.js', './manifest.json', './icon.svg', './icon-192.png', './badge-96.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network-first: data refreshes daily in season, the cache is only for offline use.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then(r => {
      const clone = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, clone));
      return r;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});

// A click only ever opens a page of this site.
const inScope = u => {
  const scope = self.registration.scope;
  try { const h = new URL(u || './', scope).href; return h.startsWith(scope) ? h : scope; } catch { return scope; }
};

// Match alerts from the notifier Worker: {title, body, url (a #/ route), tag}.
self.addEventListener('push', e => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch { m = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(m.title || 'SC BBL', {
    body: m.body || '',
    tag: m.tag,
    icon: 'icon-192.png',
    badge: 'badge-96.png',
    data: { url: inScope(m.url) },
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = inScope(e.notification.data && e.notification.data.url);
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const open = list.find(c => c.url.startsWith(self.registration.scope));
    if (!open) return self.clients.openWindow(url);
    return open.navigate(url).then(c => (c || open).focus()).catch(() => self.clients.openWindow(url));
  }));
});
