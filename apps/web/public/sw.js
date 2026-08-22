/* Auralis service worker.
 *
 * The previous build registered /sw.js while no such file existed, so every
 * page load 404'd and any worker installed earlier kept serving whatever it
 * had cached. That is the stale-page behaviour: a worker with no upgrade path
 * outlives the site it was built for.
 *
 * The rules here are chosen so a cache can never be the reason someone reads
 * an old number:
 *
 *   - HTML and API calls are NETWORK FIRST. An operations console must never
 *     answer from cache while the network is available.
 *   - Immutable build assets (/_next/static/*, fonts) are CACHE FIRST. Their
 *     URLs change when their contents change, so a hit is always correct.
 *   - CACHE bumps on every deploy and activate() deletes every older cache.
 *   - skipWaiting + clients.claim, so an update takes effect on this load
 *     rather than two navigations later.
 *   - Only GET is ever cached. Nothing else is touched.
 */

const VERSION = "auralis-v3";
const RUNTIME = `${VERSION}-runtime`;
const PRECACHE = `${VERSION}-precache`;

// Kept deliberately tiny: the offline page and the mark. Precaching routes
// would mean shipping a snapshot of live data, which is the whole problem.
const PRECACHE_URLS = ["/offline.html", "/logo.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(PRECACHE)
      .then((c) => c.addAll(PRECACHE_URLS).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== RUNTIME && k !== PRECACHE)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

/** Build output is content-hashed, so a cached hit can never be wrong. */
function isImmutable(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/fonts/") ||
    url.pathname.endsWith(".woff2")
  );
}

/** Anything whose freshness an operator would act on. */
function isLiveData(url) {
  return (
    url.pathname.startsWith("/v1/") ||
    url.pathname.startsWith("/api/") ||
    url.pathname.includes("/snapshot")
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // let cross-origin through

  // Never cache live data or event streams.
  if (isLiveData(url) || req.headers.get("accept") === "text/event-stream") return;

  if (isImmutable(url)) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(RUNTIME).then((c) => c.put(req, copy));
            }
            return res;
          })
      )
    );
    return;
  }

  // Everything else - documents included - is network first, with the cache
  // used only when the network genuinely fails.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(RUNTIME).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(async () => {
        const hit = await caches.match(req);
        if (hit) return hit;
        if (req.mode === "navigate") {
          const offline = await caches.match("/offline.html");
          if (offline) return offline;
        }
        return new Response("Offline and not cached.", {
          status: 503,
          headers: { "Content-Type": "text/plain" },
        });
      })
  );
});

// Lets the page force an immediate takeover after a deploy.
self.addEventListener("message", (event) => {
  if (event.data === "auralis:skip-waiting") self.skipWaiting();
});
