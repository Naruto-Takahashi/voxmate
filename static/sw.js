self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // ネットワーク優先（ローカルサーバーのためそのまま通す）
  event.respondWith(fetch(event.request));
});
