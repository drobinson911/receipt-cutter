const CACHE_NAME = 'receipt-cutter-v1';

const LOCAL_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/js/image-processing.js',
  '/js/pdf-generator.js',
  '/js/capture-session.js',
  '/icons/icon-192.svg',
  '/icons/icon-512.svg',
];

const CDN_ASSETS = [
  'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.2/jspdf.umd.min.js',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      await cache.addAll(LOCAL_ASSETS);
      for (const url of CDN_ASSETS) {
        try { await cache.add(url); } catch { /* CDN unavailable — ok */ }
      }
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  );
});
