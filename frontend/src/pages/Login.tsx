import { useState } from "react";
import { useAuth } from "../auth";
import TeamPicker from "../components/TeamPicker";

export default function Login() {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [teamId, setTeamId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await signup(email, password, name || undefined, teamId ?? undefined);
    } catch (err: any) {
      setError(err.message || "Error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="brand" style={{ fontSize: 30 }}>Pi<span>Scouting</span></div>
        <p className="muted" style={{ marginTop: 0 }}>Análisis y scouting de baloncesto FEB</p>

        <div className="tabs" style={{ marginBottom: 18 }}>
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Entrar</button>
          <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>Crear cuenta</button>
        </div>

        <label className="field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="field">
          <span>Contraseña</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </label>

        {mode === "signup" && (
          <>
            <label className="field">
              <span>Nombre (opcional)</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>Tu equipo</span>
              <TeamPicker value={teamId} onChange={setTeamId} />
            </label>
          </>
        )}

        {error && <div className="error-box">{error}</div>}
        <button className="primary-btn" disabled={busy}>
          {busy ? "…" : mode === "login" ? "Entrar" : "Crear cuenta"}
        </button>
      </form>
    </div>
  );
}
