/* ============================================================================
   Lo que se ve la primera vez que entras: cómo instalar la app y activar los avisos.

   No es un adorno. En iPhone, las notificaciones NO existen si la app se usa desde la
   pestaña de Safari: es una regla de Apple, no una preferencia. Así que si no se
   explica cómo añadirla a la pantalla de inicio, el push sencillamente no le llega a
   nadie, por muy bien montado que esté el servidor.
   ========================================================================== */
import { useEffect, useState } from "react";
import { IconAlert, IconBell, IconCheck } from "../icons";
import { activarPush, esIOS, esInstalada, estadoPush, type PushState } from "../push";
import { Sheet, SheetClose } from "../ui";

const VISTO = "pf_onboarding";
export const yaVisto = () => localStorage.getItem(VISTO) === "1";
export const marcarVisto = () => localStorage.setItem(VISTO, "1");

/** Icono de "Compartir" de iOS, que es el que hay que buscar en la barra de Safari. */
function IconoCompartir({ size = 17 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      style={{ verticalAlign: "-3px" }}>
      <path d="M12 15.5V3.2m0 0L8.4 6.8M12 3.2l3.6 3.6" />
      <path d="M6.5 10.5h-.8a2 2 0 0 0-2 2v6.3a2 2 0 0 0 2 2h12.6a2 2 0 0 0 2-2v-6.3a2 2 0 0 0-2-2h-.8" />
    </svg>
  );
}

export default function Onboarding({ onClose }: { onClose: () => void }) {
  const [estado, setEstado] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { estadoPush().then(setEstado); }, []);

  async function activar() {
    setBusy(true);
    try { setEstado(await activarPush()); } finally { setBusy(false); }
  }

  function cerrar() { marcarVisto(); onClose(); }

  const instalada = esInstalada();
  const ios = esIOS();

  return (
    <Sheet onClose={cerrar} title="Bienvenido a PiFantasy">
      <div className="sheet__head" style={{ marginBottom: 14 }}>
        <div className="sheet__body">
          <h2>Que no se te escape nada</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            Dos minutos y lo tienes como una app de verdad.
          </div>
        </div>
        <SheetClose onClose={cerrar} />
      </div>

      {/* Paso 1: instalar. Solo tiene sentido si aún no está instalada. */}
      {!instalada && (
        <div className="step2">
          <span className="step2__n">1</span>
          <div>
            <b>Añádela a la pantalla de inicio</b>
            {ios ? (
              <p>
                En Safari, toca <IconoCompartir /> <b>Compartir</b> abajo, baja y elige{" "}
                <b>Añadir a pantalla de inicio</b>. Se abrirá a pantalla completa, sin la
                barra del navegador.
              </p>
            ) : (
              <p>
                En el menú del navegador, elige <b>Instalar aplicación</b> o{" "}
                <b>Añadir a pantalla de inicio</b>.
              </p>
            )}
            {ios && (
              <p className="step2__ojo">
                En iPhone este paso no es opcional para los avisos: Apple no permite
                notificaciones desde la pestaña del navegador.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Paso 2: avisos */}
      <div className="step2">
        <span className="step2__n">{instalada ? 1 : 2}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <b>Activa los avisos</b>
          <p>
            Te avisamos cuando te clausulan a alguien, cuando pierdes una puja y cuando se
            puntúa la jornada. Nada más: el mercado abre todos los días y no vamos a
            darte la lata con eso.
          </p>

          {estado === "activado" && (
            <p className="step2__ok"><IconCheck size={15} /> Avisos activados en este dispositivo.</p>
          )}
          {estado === "instalar" && (
            <p className="step2__ojo">
              Primero añádela a la pantalla de inicio, ábrela desde su icono y vuelve aquí.
            </p>
          )}
          {estado === "bloqueado" && (
            <p className="step2__ojo">
              <IconAlert size={14} /> Los tienes bloqueados. Se cambia en los ajustes del
              teléfono, en las notificaciones de PiFantasy.
            </p>
          )}
          {estado === "no-soportado" && (
            <p className="step2__ojo">Este navegador no admite avisos. La app funciona igual.</p>
          )}
          {estado === "desactivado" && (
            <button className="btn btn--block" disabled={busy} onClick={activar}>
              {busy ? <span className="spinner" /> : <><IconBell size={17} />Activar los avisos</>}
            </button>
          )}
        </div>
      </div>

      <button className="btn btn--ghost btn--block" style={{ marginTop: 14 }} onClick={cerrar}>
        {estado === "activado" ? "Listo, vamos allá" : "Ahora no"}
      </button>
      <p className="hint" style={{ textAlign: "center", marginTop: 10 }}>
        Puedes volver a esto cuando quieras desde <b>Ajustes</b>.
      </p>
    </Sheet>
  );
}
