import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import { Loading, applyTheme, readTheme } from "./ui";
import Login from "./screens/Login";
import { Reset } from "./screens/Password";
import Home from "./screens/Home";
import League from "./screens/League";

// El tema se aplica antes del primer render para que no haya destello blanco al abrir.
applyTheme(readTheme());

export type Me = { id: number; email: string; name?: string | null; is_admin?: boolean };

export default function App() {
  const [booted, setBooted] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [leagueId, setLeagueId] = useState<number | null>(null);
  // el enlace del correo llega como /?reset=TOKEN
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get("reset"));

  useEffect(() => {
    if (!getToken()) { setBooted(true); return; }
    api.me().then(setMe).catch(() => setToken(null)).finally(() => setBooted(true));
  }, []);

  function logout() {
    setToken(null);
    setMe(null);
    setLeagueId(null);
  }

  if (!booted) return <div className="centered"><Loading label="Abriendo PiFantasy" /></div>;
  // el enlace manda por encima de todo: puede llegar con otra sesión abierta
  if (resetToken) {
    return <Reset token={resetToken} onDone={(m) => { setResetToken(null); setMe(m); }} />;
  }
  if (!me) return <Login onAuth={setMe} />;
  if (leagueId) return <League id={leagueId} me={me} onBack={() => setLeagueId(null)} />;
  return <Home me={me} onOpen={setLeagueId} onLogout={logout} />;
}
