/* The workbench's service worker: the page shell (index, css, js, manifest, icons) is kept in
   a cache so the app opens from the home screen without the server, and is fetched network-first
   so a running server always wins. Everything else -- the API, the event stream, images and
   files -- is the workspace's live state and goes straight to the network. */
const CACHE = 'tcg-mint-shell-v1';
const SHELL = ['/', '/static/app.css', '/static/app.js', '/manifest.webmanifest', '/static/icon-192.png', '/static/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  const shell = e.request.mode === 'navigate' || url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest';
  if (!shell) return;
  const key = e.request.mode === 'navigate' ? '/' : url.pathname;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
    return r;
  }).catch(() => caches.match(key).then(r => r || new Response('the workbench is not running', {status: 503, headers: {'Content-Type': 'text/plain'}}))));
});
