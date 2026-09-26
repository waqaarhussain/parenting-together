const CACHE = "parenting-together-v2";
const STATIC = ["/", "/static/app.css", "/static/app.js", "/static/icon.svg", "/static/manifest.webmanifest"];
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
