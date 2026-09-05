/* Service worker de PiFantasy.

   Solo hace una cosa: recibir las notificaciones cuando la app está cerrada y abrirla
   al tocarlas. No cachea nada a propósito — una app cuyos datos cambian cada minuto
   (mercado, pujas, jornada en juego) sirviendo contenido viejo desde la caché es peor
   que una que tarda medio segundo más en cargar. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let d = { title: "PiFantasy", body: "", url: "/" };
  try {
    if (event.data) d = { ...d, ...event.data.json() };
  } catch (_) {
    if (event.data) d.body = event.data.text();
  }
  event.waitUntil(self.registration.showNotification(d.title, {
    body: d.body,
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    // mismo tag: un aviso nuevo sustituye al anterior en vez de apilar diez
    tag: "pifantasy",
    renotify: true,
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destino = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const abiertas = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    // si la app ya está abierta, se trae al frente en vez de abrir otra pestaña
    for (const c of abiertas) {
      if (c.url.includes(self.location.origin)) {
        await c.focus();
        if ("navigate" in c && destino !== "/") await c.navigate(destino);
        return;
      }
    }
    await self.clients.openWindow(destino);
  })());
});
