const VERSION = new URL(self.location.href).searchParams.get("v") || "dev";
const VERSION_QUERY = "?v=" + encodeURIComponent(VERSION);
const CACHE = "parenting-together-" + VERSION;
const STATIC = ["/" + VERSION_QUERY, "/static/app.css" + VERSION_QUERY, "/static/vault.js" + VERSION_QUERY, "/static/app.js" + VERSION_QUERY, "/static/icon.svg", "/static/manifest.webmanifest"];
self.addEventListener("install", function(event) {
  event.waitUntil(caches.open(CACHE).then(function(cache) { return cache.addAll(STATIC); }));
  self.skipWaiting();
});
self.addEventListener("activate", function(event) {
  event.waitUntil(caches.keys().then(function(keys) {
    return Promise.all(keys.filter(function(k) { return k !== CACHE; }).map(function(k) { return caches.delete(k); }));
  }));
  self.clients.claim();
});
self.addEventListener("fetch", function(event) {
  if (event.request.method !== "GET" || new URL(event.request.url).pathname.startsWith("/api/")) return;
  event.respondWith(fetch(event.request).then(function(response) {
    var copy = response.clone();
    caches.open(CACHE).then(function(cache) { cache.put(event.request, copy); });
    return response;
  }).catch(function() { return caches.match(event.request); }));
});
