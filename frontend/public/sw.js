// MEMESCOPE service worker: shows real-wallet trade alerts pushed by the API.
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || "MEMESCOPE", {
    body: data.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    data: { url: data.url || "/real-wallet" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/real-wallet";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
    for (const tab of tabs) if ("focus" in tab) { tab.navigate(url); return tab.focus(); }
    return self.clients.openWindow(url);
  }));
});
