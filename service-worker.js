const SHELL_CACHE = "ashare-shell-20260723-freshness-2";
const DATA_CACHE = "ashare-data-20260723-freshness-2";
const ROOT_URL = new URL("./", self.location.href);
const MOBILE_URL = new URL("mobile/index.html", ROOT_URL).href;
const APP_SHELL = [
  MOBILE_URL,
  new URL("mobile/styles.css?v=20260723-freshness2", ROOT_URL).href,
  new URL("mobile/app.js?v=20260723-freshness2", ROOT_URL).href,
  new URL("mobile/manifest.webmanifest", ROOT_URL).href,
  new URL("icons/icon-192.png", ROOT_URL).href,
  new URL("icons/icon-512.png", ROOT_URL).href,
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => ![SHELL_CACHE, DATA_CACHE].includes(key)).map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

async function latestSnapshot(request) {
  const cache = await caches.open(DATA_CACHE);
  const canonical = new Request(new URL("data/mobile_snapshot.enc.json", ROOT_URL).href);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(canonical, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(canonical);
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.endsWith("/data/mobile_snapshot.enc.json")) {
    event.respondWith(latestSnapshot(event.request));
    return;
  }
  if (url.pathname.includes("/api/")) {
    event.respondWith(networkFirst(event.request, DATA_CACHE));
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(
      networkFirst(event.request, SHELL_CACHE).catch(() => caches.match(MOBILE_URL)),
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || networkFirst(event.request, SHELL_CACHE)),
  );
});
