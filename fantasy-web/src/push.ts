/* ============================================================================
   Avisos en el móvil (Web Push).

   En iPhone hay una regla de Apple que manda sobre todo lo demás: las notificaciones
   web SOLO funcionan si la app está añadida a la pantalla de inicio. Desde la pestaña
   normal de Safari no se pueden ni pedir. Por eso aquí se distingue "no se puede" de
   "aún no lo has activado": son cosas muy distintas de cara al usuario.
   ========================================================================== */
import { api } from "./api";

export type PushState =
  | "no-soportado"     // el navegador no sabe de esto
  | "instalar"         // iPhone en Safari: hay que añadirla a la pantalla de inicio
  | "desactivado"      // se puede activar
  | "bloqueado"        // el usuario dijo que no; hay que ir a los ajustes del sistema
  | "activado";

export const esIOS = () =>
  /iphone|ipad|ipod/i.test(navigator.userAgent)
  // iPad moderno se hace pasar por Mac, pero con pantalla táctil
  || (navigator.platform === "MacIntel" && (navigator as any).maxTouchPoints > 1);

/** ¿Está abierta como app instalada y no como pestaña del navegador? */
export const esInstalada = () =>
  window.matchMedia("(display-mode: standalone)").matches
  || (navigator as any).standalone === true;

export function soportaPush() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function estadoPush(): Promise<PushState> {
  if (!soportaPush()) return esIOS() && !esInstalada() ? "instalar" : "no-soportado";
  // iOS solo expone el permiso cuando corre como app instalada
  if (esIOS() && !esInstalada()) return "instalar";
  if (Notification.permission === "denied") return "bloqueado";
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    const sub = await reg?.pushManager.getSubscription();
    return sub ? "activado" : "desactivado";
  } catch {
    return "desactivado";
  }
}

/** base64url -> Uint8Array, que es lo que pide el navegador para la clave VAPID. */
function claveABytes(base64: string) {
  const pad = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export async function registrarSW() {
  if (!("serviceWorker" in navigator)) return null;
  try { return await navigator.serviceWorker.register("/sw.js"); }
  catch { return null; }
}

/**
 * Pide permiso y suscribe este dispositivo. Devuelve el estado en que queda, para que
 * la interfaz pueda decir qué ha pasado en vez de quedarse callada.
 */
export async function activarPush(): Promise<PushState> {
  if (!soportaPush()) return "no-soportado";
  if (esIOS() && !esInstalada()) return "instalar";

  const permiso = await Notification.requestPermission();
  if (permiso !== "granted") return permiso === "denied" ? "bloqueado" : "desactivado";

  const { enabled, key } = await api.pushKey();
  if (!enabled || !key) return "no-soportado";

  const reg = (await navigator.serviceWorker.getRegistration()) ?? (await registrarSW());
  if (!reg) return "no-soportado";
  await navigator.serviceWorker.ready;

  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,               // obligatorio: nada de push silencioso
    applicationServerKey: claveABytes(key),
  });
  const j: any = sub.toJSON();
  await api.pushSubscribe({
    endpoint: sub.endpoint,
    p256dh: j.keys.p256dh,
    auth: j.keys.auth,
    user_agent: navigator.userAgent,
  });
  return "activado";
}

export async function desactivarPush() {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await api.pushUnsubscribe(sub.endpoint).catch(() => {});
  await sub.unsubscribe().catch(() => {});
}
