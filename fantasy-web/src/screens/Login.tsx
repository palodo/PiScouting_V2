import { useEffect, useState } from "react";
import { api, setToken } from "../api";
import type { Me } from "../App";
import { IconAlert } from "../icons";
import GoogleButton from "../GoogleButton";
import { Forgot } from "./Password";
import { Brand, Segmented } from "../ui";

export default function Login({ onAuth }: { onAuth: (me: Me) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [googleId, setGoogleId] = useState<string | null>(null);
  const [olvidada, setOlvidada] = useState(false);

  // si el backend no tiene Google configurado, ni se carga su script
  useEffect(() => {
    api.authConfig().then((c) => setGoogleId(c.google_client_id)).catch(() => {});
  }, []);

  async function entrarConGoogle(idToken: string) {
    setErr(null); setBusy(true);
    try {
      const r = await api.google(idToken);
      setToken(r.token);
      onAuth(await api.me());
    } catch (e: any) {
      setErr(e.message);
    } finally { setBusy(false); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = mode === "login"
        ? await api.login(email.trim(), pass)
        : await api.signup(email.trim(), pass);
      setToken(r.token);
      onAuth(await api.me());
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (olvidada) return <Forgot onBack={() => setOlvidada(false)} />;

  return (
    <div className="centered">
      <form onSubmit={submit} style={{ width: "100%", maxWidth: 400 }}>
        <div className="login__head">
          <Brand size={54} />
          <p className="login__tag">Fantasy de baloncesto FEB · 1ª, 2ª y 3ª</p>
        </div>

        <Segmented value={mode} onChange={setMode} options={[
          { v: "login", label: "Entrar" },
          { v: "signup", label: "Crear cuenta" },
        ]} />

        <div style={{ height: 18 }} />

        <label className="field">
          <span className="field__label">Email</span>
          <input className="input" type="email" value={email} required autoComplete="email"
            inputMode="email" placeholder="tu@email.com"
            onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Contraseña</span>
          <input className="input" type="password" value={pass} required
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            placeholder="••••••••"
            onChange={(e) => setPass(e.target.value)} />
        </label>

        {mode === "login" && (
          <button type="button" className="linkbtn" style={{ marginTop: -6, marginBottom: 6 }}
            onClick={() => setOlvidada(true)}>¿Has olvidado tu contraseña?</button>
        )}

        {err && <div className="formerr"><IconAlert size={17} />{err}</div>}

        <button className="btn btn--block btn--lg" disabled={busy}>
          {busy ? <span className="spinner" /> : mode === "login" ? "Entrar" : "Crear cuenta"}
        </button>

        {googleId && (
          <>
            <div className="orsep"><span>o</span></div>
            <GoogleButton clientId={googleId} onToken={entrarConGoogle} onError={setErr} />
            <p className="hint" style={{ textAlign: "center", margin: "12px 0 0" }}>
              Con Google no hay contraseña que recordar. Si es tu primera vez, te crea la
              cuenta con ese email.
            </p>
          </>
        )}
      </form>
    </div>
  );
}
