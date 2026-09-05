/* ============================================================================
   Botón de "Continuar con Google" (Google Identity Services).

   El script y el botón los pinta Google: sus normas de marca no permiten dibujarlo
   por nuestra cuenta. Solo aparece si el backend dice que hay un GOOGLE_CLIENT_ID
   configurado, así que en un despliegue sin Google no se carga ni el script.
   ========================================================================== */
import { useEffect, useRef, useState } from "react";

const SRC = "https://accounts.google.com/gsi/client";

/** Carga el script una sola vez, aunque el componente se monte varias veces. */
function loadGis(): Promise<any> {
  const w = window as any;
  if (w.google?.accounts?.id) return Promise.resolve(w.google);
  if (!w.__gisPromise) {
    w.__gisPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SRC;
      s.async = true;
      s.onload = () => resolve((window as any).google);
      s.onerror = () => reject(new Error("No se pudo cargar Google"));
      document.head.appendChild(s);
    });
  }
  return w.__gisPromise;
}

export default function GoogleButton({ clientId, onToken, onError }: {
  clientId: string;
  onToken: (idToken: string) => void;
  onError: (msg: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [fallo, setFallo] = useState(false);
  // en un ref para que el callback de Google use siempre el último, sin repintar el botón
  const cb = useRef(onToken);
  cb.current = onToken;

  useEffect(() => {
    let vivo = true;
    loadGis().then((google) => {
      if (!vivo || !box.current) return;
      const oscuro = window.matchMedia("(prefers-color-scheme: dark)").matches
        || document.documentElement.getAttribute("data-theme") === "dark";
      google.accounts.id.initialize({
        client_id: clientId,
        callback: (r: any) => r?.credential ? cb.current(r.credential)
          : onError("Google no devolvió ninguna credencial"),
      });
      google.accounts.id.renderButton(box.current, {
        type: "standard", theme: oscuro ? "filled_black" : "outline",
        size: "large", text: "continue_with", shape: "pill", locale: "es",
        width: Math.min(400, Math.round(box.current.getBoundingClientRect().width) || 320),
      });
    }).catch(() => { if (vivo) setFallo(true); });
    return () => { vivo = false; };
  }, [clientId, onError]);

  if (fallo) return null;   // sin conexión con Google, se entra con email como siempre
  return <div className="gbtn" ref={box} />;
}
