// 実行リストの service worker（0.1.0）。画面の部品だけ手元に持つ。データ（/api/）は毎回読む・持たない（仕様 6章）
const CACHE = "kartelog-0.3.5";
const SHELL = ["/kartelog/", "/kartelog/style.css", "/kartelog/app.js", "/kartelog/icon.svg", "/kartelog/robot.png", "/kartelog/icon-192.png", "/kartelog/manifest.webmanifest"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin || !u.pathname.startsWith("/kartelog/") || u.pathname.startsWith("/kartelog/api/") || e.request.method !== "GET") return;
  // 新しい版を先に取りにいき、つながらないときだけ手元の部品を出す
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && r.type === "basic") { const c = r.clone(); caches.open(CACHE).then((x) => x.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
