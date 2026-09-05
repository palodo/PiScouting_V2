/* ============================================================================
   Recuperar contraseña: pedir el enlace y ponerse una nueva.

   Funciona con y sin correo configurado. Si el servidor no puede enviar, se dice la
   verdad y se manda a pedirle el enlace al administrador, en vez de dejar a la gente
   esperando un email que no va a llegar.
   ========================================================================== */
import { useState } from "react";
import { api, setToken } from "../api";
import type { Me } from "../App";
import { IconAlert, IconArrowLeft, IconCheck } from "../icons";
import { Brand } from "../ui";

/* ------------------------------------------------------- pedir el enlace */
export function Forgot({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ sent: boolean; mail_enabled: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try { setRes(await api.forgot(email.trim())); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  if (res) {
    return (
      <div className="centered">
        <div style={{ width: "100%", maxWidth: 400 }}>
          <div className="login__head"><Brand size={46} /></div>
          <div className="card card--pad" style={{ textAlign: "center" }}>
            <span className="empty__ico" style={{ margin: "0 auto 10px", color: "var(--pos)" }}>
              <IconCheck size={22} />
            </span>
            {res.mail_enabled ? <>
              <h2 style={{ fontSize: "var(--fs-lg)", marginBottom: 6 }}>Mira tu correo</h2>
              <p className="hint" style={{ margin: 0 }}>
                Si <b>{email.trim()}</b> tiene cuenta, le acaba de llegar un enlace para poner
                una contraseña nueva. Caduca en 30 minutos. Revisa también el spam.
              </p>
            </> : <>
              <h2 style={{ fontSize: "var(--fs-lg)", marginBottom: 6 }}>Pídeselo al administrador</h2>
              <p className="hint" style={{ margin: 0 }}>
                Todavía no se mandan correos automáticos. Escribe a quien lleva la liga y que
                te genere un enlace de recuperación: lo tiene a un toque en la app.
              </p>
            </>}
          </div>
          <button className="btn btn--ghost btn--block" style={{ marginTop: 14 }} onClick={onBack}>
            Volver a entrar
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="centered">
      <form onSubmit={submit} style={{ width: "100%", maxWidth: 400 }}>
        <button type="button" className="linkbtn" onClick={onBack}>
          <IconArrowLeft size={18} />Volver
        </button>
        <div className="login__head" style={{ marginTop: 10 }}>
          <Brand size={46} />
          <p className="login__tag">¿Has olvidado tu contraseña?</p>
        </div>
        <label className="field">
          <span className="field__label">Tu email</span>
          <input className="input" type="email" value={email} required autoComplete="email"
            inputMode="email" placeholder="tu@email.com"
            onChange={(e) => setEmail(e.target.value)} />
        </label>
        {err && <div className="formerr"><IconAlert size={17} />{err}</div>}
        <button className="btn btn--block btn--lg" disabled={busy}>
          {busy ? <span className="spinner" /> : "Enviarme un enlace"}
        </button>
      </form>
    </div>
  );
}

/* --------------------------------------------- poner la contraseña nueva */
export function Reset({ token, onDone }: { token: string; onDone: (me: Me) => void }) {
  const [pass, setPass] = useState("");
  const [pass2, setPass2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const corta = pass.length > 0 && pass.length < 6;
  const distintas = pass2.length > 0 && pass !== pass2;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const r = await api.resetPassword(token, pass);
      setToken(r.token);           // el enlace ya te deja dentro, sin volver a escribirla
      history.replaceState(null, "", "/");
      onDone(await api.me());
    } catch (e: any) {
      setErr(e.message);
    } finally { setBusy(false); }
  }

  return (
    <div className="centered">
      <form onSubmit={submit} style={{ width: "100%", maxWidth: 400 }}>
        <div className="login__head">
          <Brand size={46} />
          <p className="login__tag">Pon una contraseña nueva</p>
        </div>
        <label className="field">
          <span className="field__label">Contraseña nueva</span>
          <input className="input" type="password" value={pass} required autoComplete="new-password"
            placeholder="Mínimo 6 caracteres" onChange={(e) => setPass(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Repítela</span>
          <input className="input" type="password" value={pass2} required autoComplete="new-password"
            placeholder="••••••••" onChange={(e) => setPass2(e.target.value)} />
        </label>
        {corta && <p className="hint" style={{ margin: "-6px 0 12px" }}>Al menos 6 caracteres.</p>}
        {distintas && <p className="hint" style={{ margin: "-6px 0 12px" }}>No coinciden.</p>}
        {err && <div className="formerr"><IconAlert size={17} />{err}</div>}
        <button className="btn btn--block btn--lg" disabled={busy || corta || distintas || !pass2}>
          {busy ? <span className="spinner" /> : "Guardar y entrar"}
        </button>
        <p className="hint" style={{ textAlign: "center", marginTop: 12 }}>
          Al guardarla entras directamente, sin tener que escribirla otra vez.
        </p>
      </form>
    </div>
  );
}
