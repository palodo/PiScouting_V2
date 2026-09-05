import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import { Loading, applyTheme, readTheme } from "./ui";
import Login from "./screens/Login";
import { Reset } from "./screens/Password";
import Onboarding, { marcarVisto, yaVisto } from "./screens/Onboarding";
import Diag from "./screens/Diag";
import { esInstalada, registrarSW } from "./push";
import Home from "./screens/Home";
import League from "./screens/League";

// El tema se aplica antes del primer render para que no haya destello blanco al abrir.
applyTheme(readTheme());
// Instalada en la pantalla de inicio: solo entonces hay que respetar el hueco del
// indicador de inicio (ver --safe-b en index.css).
document.documentElement.classList.toggle("is-standalone", esInstalada());

export type Me = { id: number; email: string; name?: string | null; is_admin?: boolean };

export default function App() {
  const [booted, setBooted] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [leagueId, setLeagueId] = useState<number | null>(null);
  // el enlace del correo llega como /?reset=TOKEN
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get("reset"));
  const [bienvenida, setBienvenida] = useState(false);

  // el service worker se registra siempre: sin él no hay avisos, y no estorba
  useEffect(() => { registrarSW(); }, []);
  // la bienvenida, solo la primera vez que se entra con sesión
  useEffect(() => { if (me && !yaVisto()) setBienvenida(true); }, [me]);

  useEffect(() => {
    if (!getToken()) { setBooted(true); return; }
    api.me().then(setMe).catch(() => setToken(null)).finally(() => setBooted(true));
  }, []);

  function logout() {
    setToken(null);
    setMe(null);
    setLeagueId(null);
  }

  // /?diag=1 — medidas reales de la pantalla, para arreglar el layout del móvil con
  // números en vez de a ojo. No hace falta sesión.
  if (new URLSearchParams(window.location.search).has("diag")) return <Diag />;

  if (!booted) return <div className="centered"><Loading label="Abriendo PiFantasy" /></div>;
  // el enlace manda por encima de todo: puede llegar con otra sesión abierta
  if (resetToken) {
    return <Reset token={resetToken} onDone={(m) => { setResetToken(null); setMe(m); }} />;
  }
  if (!me) return <Login onAuth={setMe} />;

  const bienve = bienvenida
    ? <Onboarding onClose={() => { marcarVisto(); setBienvenida(false); }} />
    : null;
  if (leagueId) {
    return <>{bienve}<League id={leagueId} me={me} onBack={() => setLeagueId(null)} /></>;
  }
  return <>{bienve}<Home me={me} onOpen={setLeagueId} onLogout={logout} /></>;
}
