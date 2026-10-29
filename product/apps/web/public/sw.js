/*
 * FOCUS service worker — app shell only.
 *
 * Deliberately narrow:
 *  - never caches API responses, audio, transcripts, thumbnails or uploads
 *  - never caches cross-origin requests (the API lives on another origin)
 *  - never caches requests that carry an Authorization header
 *
 * The processing itself always needs the server; the app says so in the UI.
 */

const SHELL_CACHE = 'focus-shell-v1';
const SHELL_ASSETS = ['/', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

function isPrivateRequest(request, url) {
  if (url.origin !== self.location.origin) return true;
  if (request.headers.has('authorization')) return true;
  if (request.headers.has('range')) return true;
  if (request.destination === 'audio' || request.destination === 'video') return true;
  if (url.pathname.startsWith('/api/')) return true;
  return false;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (isPrivateRequest(request, url)) return;

  // Navigations: network first so a new deploy is picked up, shell as offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match('/').then((cached) => cached ?? Response.error()),
      ),
    );
    return;
  }

  // Static assets: stale-while-revalidate.
  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/icons/')) {
    event.respondWith(
      caches.open(SHELL_CACHE).then(async (cache) => {
        const cached = await cache.match(request);
        const network = fetch(request)
          .then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          })
          .catch(() => cached ?? Response.error());
        return cached ?? network;
      }),
    );
  }
});
