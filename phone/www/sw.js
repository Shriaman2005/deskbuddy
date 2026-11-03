// Chip's service worker does nothing on purpose: no cache, no offline copy, every request goes to the network. Chrome only
// offers "Install app" for a page that has one with a fetch handler. A deploy changes version.txt, and the page reloads itself.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
