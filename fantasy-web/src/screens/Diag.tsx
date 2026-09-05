/* ============================================================================
   Pantalla de diagnóstico de pantalla (/?diag=1).

   Los problemas de "se pierde una franja abajo" en iOS no se pueden reproducir desde
   un ordenador: dependen del alto real del visor, de si la app va instalada y de los
   márgenes de seguridad que reporta el sistema. Esto los enseña tal cual, para poder
   arreglar con números en vez de a ojo.
   ========================================================================== */
import { useEffect, useState } from "react";

function insets() {
  // se leen con un elemento de prueba: env() no es accesible desde JavaScript
  const probe = document.createElement("div");
  probe.style.cssText = "position:fixed;top:0;left:0;visibility:hidden;"
    + "padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom);"
    + "padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right)";
  document.body.appendChild(probe);
  const cs = getComputedStyle(probe);
  const v = {
    top: cs.paddingTop, bottom: cs.paddingBottom, left: cs.paddingLeft, right: cs.paddingRight,
  };
  probe.remove();
  return v;
}

export default function Diag() {
  const [, refrescar] = useState(0);
  useEffect(() => {
    const f = () => refrescar((n) => n + 1);
    window.addEventListener("resize", f);
    window.visualViewport?.addEventListener("resize", f);
    return () => {
      window.removeEventListener("resize", f);
      window.visualViewport?.removeEventListener("resize", f);
    };
  }, []);

  const env = insets();
  const raiz = getComputedStyle(document.documentElement);
  const datos: [string, string][] = [
    ["window.innerHeight", `${window.innerHeight}`],
    ["visualViewport", `${Math.round(window.visualViewport?.height ?? 0)}`],
    ["screen.height", `${window.screen.height}`],
    ["devicePixelRatio", `${window.devicePixelRatio}`],
    ["100dvh mide", getComputedStyle(document.documentElement).height],
    ["env top / bottom", `${env.top} / ${env.bottom}`],
    ["env left / right", `${env.left} / ${env.right}`],
    ["--safe-t / --safe-b", `${raiz.getPropertyValue("--safe-t").trim() || "0px"} / ${raiz.getPropertyValue("--safe-b").trim() || "0px"}`],
    ["display-mode standalone", String(window.matchMedia("(display-mode: standalone)").matches)],
    ["navigator.standalone", String((navigator as any).standalone)],
    ["clase is-standalone", String(document.documentElement.classList.contains("is-standalone"))],
    ["userAgent", navigator.userAgent],
  ];
  const texto = datos.map(([k, v]) => `${k}: ${v}`).join("\n");

  return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column",
      background: "var(--bg)", color: "var(--text)" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: "calc(12px + var(--safe-t)) 14px 14px" }}>
        <h1 style={{ fontSize: 20, marginBottom: 10 }}>Diagnóstico de pantalla</h1>
        <div style={{ border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
          {datos.map(([k, v]) => (
            <div key={k} style={{ display: "flex", gap: 10, padding: "8px 12px",
              borderTop: "1px solid var(--border)", fontSize: 12, background: "var(--surface)" }}>
              <span style={{ color: "var(--text-3)", flex: "0 0 45%" }}>{k}</span>
              <span style={{ flex: 1, wordBreak: "break-all", fontWeight: 700 }}>{v}</span>
            </div>
          ))}
        </div>
        <button className="btn btn--block" style={{ marginTop: 14 }}
          onClick={() => navigator.clipboard?.writeText(texto)}>Copiar para pegárselo a Claude</button>
        <p className="hint" style={{ marginTop: 12 }}>
          La franja naranja de abajo imita la barra de pestañas. Si la ves entera y pegada
          al borde inferior, el cálculo es correcto. Si se pierde por debajo o queda un
          hueco, no lo es.
        </p>
        <div style={{ height: 400 }} />
        <p className="hint">Esto es para comprobar el desplazamiento. Sigue bajando.</p>
      </div>

      {/* imitación de la barra de pestañas, con la misma fórmula */}
      <div style={{ flex: "0 0 auto", paddingBottom: "var(--safe-b)",
        background: "var(--accent)", color: "var(--accent-ink)",
        borderTop: "2px solid var(--text)" }}>
        <div style={{ height: 58, display: "flex", alignItems: "center",
          justifyContent: "center", fontWeight: 800, fontSize: 13 }}>
          BARRA · ¿la ves entera y pegada al borde?
        </div>
        <div style={{ textAlign: "center", fontSize: 10, fontWeight: 700, opacity: 0.75 }}>
          fin del hueco de seguridad
        </div>
      </div>
    </div>
  );
}
