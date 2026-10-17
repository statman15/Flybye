// One service worker for both jobs: the offline shell (network-first, like HypertroPhy) and web push (FCM).
// Firebase's own messaging worker is not needed: FCM delivers {notification, data, fcmOptions} and we draw it here.
// ponytail: network-first waits on a slow connection before falling back; switch to stale-while-revalidate if that hurts.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));

self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const url = new URL(r.url);
  if (url.hostname === 'www.gstatic.com') { // Firebase SDK, pinned version in the URL: cache-first forever
    e.respondWith(caches.open('sdk').then(async c => (await c.match(r)) || fetch(r).then(res => {
      if (res.ok) c.put(r, res.clone());
      return res;
    })));
  } else if (url.origin === location.origin) {
    e.respondWith(fetch(r).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open('app').then(c => c.put(r, copy)); }
      return res;
    }).catch(() => caches.match(r, { ignoreSearch: true })));
  }
});

self.addEventListener('push', e => {
  const p = e.data?.json() ?? {}, n = p.notification ?? {}, d = p.data ?? {};
  const link = p.fcmOptions?.link || (d.window_id ? `${registration.scope}#trip=${d.window_id}|${d.code}` : registration.scope);
  e.waitUntil(registration.showNotification(n.title || 'Flybye', { body: n.body || '', icon: 'icon-192.png', data: { link } }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const link = e.notification.data?.link || registration.scope;
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async list => {
    const open = list[0];
    if (!open) return clients.openWindow(link);
    await open.focus();
    open.postMessage({ hash: new URL(link).hash });
  }));
});
