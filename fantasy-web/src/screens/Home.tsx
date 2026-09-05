import { useEffect, useState } from "react";
import { api } from "../api";
import type { Me } from "../App";
import { IconAlert, IconArrowLeft, IconLogout, IconTrophy } from "../icons";
import { phaseInfo } from "../parts";
import { Brand, Empty, Segmented, SkeletonList, Section, useThemeMode, type ThemeMode } from "../ui";
import NotificationBell from "./Notifications";
import { activarPush, desactivarPush, estadoPush, type PushState } from "../push";
import { IconBell } from "../icons";

const DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];

const monogram = (s: string) =>
  s.trim().split(/\s+/).filter((w) => w.length > 2).slice(0, 2).map((w) => w[0]).join("").toUpperCase()
  || s.trim().slice(0, 2).toUpperCase();

export default function Home({ me, onOpen, onLogout, invitacion, onInvitacionUsada }: {
  me: Me; onOpen: (id: number) => void; onLogout: () => void;
  invitacion?: string | null; onInvitacionUsada?: () => void;
}) {
  const [leagues, setLeagues] = useState<any[] | null>(null);
  const [view, setView] = useState<"list" | "create" | "join">(invitacion ? "join" : "list");
  const [theme, setTheme] = useThemeMode();

  useEffect(() => { api.leagues().then(setLeagues).catch(() => setLeagues([])); }, [view]);

  return (
    <div className="shell">
      <header className="appbar">
        <div className="appbar__in appbar__in--flat">
          <div className="appbar__nav">
            {view === "list"
              ? <Brand size={30} />
              : <button className="linkbtn" onClick={() => setView("list")}>
                  <IconArrowLeft size={18} />Mis ligas
                </button>}
            <span style={{ flex: 1 }} />
            {view === "list" && <>
              <NotificationBell />
              <button className="iconbtn" onClick={onLogout} aria-label="Cerrar sesión">
                <IconLogout size={19} />
              </button>
            </>}
          </div>
        </div>
      </header>

      <main className="wrap">
        {view === "list" && (
          <>
            <Section right={leagues ? String(leagues.length) : undefined}>Tus ligas</Section>
            {leagues === null && <SkeletonList n={2} />}
            {leagues?.length === 0 && (
              <Empty icon={<IconTrophy size={22} />} title="Todavía no juegas ninguna liga">
                Crea una liga y comparte el código con tu grupo, o únete a la de un amigo.
              </Empty>
            )}
            {leagues?.map((l) => (
              <button key={l.id} className="leaguecard" onClick={() => onOpen(l.id)}>
                <div className="leaguecard__top">
                  <span className="mono">{monogram(l.name)}</span>
                  <span className="leaguecard__id">
                    <b>{l.name}</b>
                    <span>{l.competition}{l.grupo ? ` · ${l.grupo}` : ""}</span>
                  </span>
                  {l.market_open
                    ? <span className="badge badge--live"><span className="livedot" />Mercado</span>
                    : <span className="badge">{phaseInfo(l).chip}</span>}
                </div>
                <div className="leaguecard__stats">
                  <div><b className="num">{l.member_points}</b><span>tus puntos</span></div>
                  <div><b className="num">{l.members}</b><span>mánagers</span></div>
                  <div><b className="num">{l.current_jornada}/{l.max_jornada}</b><span>jornada</span></div>
                </div>
              </button>
            ))}

            <div className="grid2" style={{ marginTop: 16 }}>
              <button className="btn" onClick={() => setView("create")}>Crear liga</button>
              <button className="btn btn--ghost" onClick={() => setView("join")}>Unirme</button>
            </div>

            <Section>Ajustes</Section>
            <div className="card card--pad">
              <span className="field__label">Aspecto</span>
              <Segmented<ThemeMode> value={theme} onChange={setTheme} options={[
                { v: "auto", label: "Automático" },
                { v: "light", label: "Claro" },
                { v: "dark", label: "Oscuro" },
              ]} />
              <p className="hint" style={{ margin: "10px 0 0" }}>
                Sesión iniciada como <b>{me.email}</b>{me.is_admin ? " · administrador" : ""}.
              </p>
            </div>

            <Avisos />

            {me.is_admin && <>
              <Section>Administración</Section>
              <ResetLinkTool />
            </>}
          </>
        )}

        {view === "create" && <CreateLeague onDone={onOpen} />}
        {view === "join" && <JoinLeague onDone={onOpen} inicial={invitacion} onUsada={onInvitacionUsada} />}
      </main>
    </div>
  );
}

/* -------------------------------------------------------------- crear liga */
function CreateLeague({ onDone }: { onDone: (id: number) => void }) {
  const [comps, setComps] = useState<any[]>([]);
  const [f, setF] = useState({
    name: "", manager_name: "", competition: "", grupo: "",
    market_weekday: 4, market_hour: 20, market_duration_h: 24, market_size: 10,
    budget: 100, squad_size: 10, lineup_size: 5, initial_squad: 5,
    clause_factor: 2.0, clause_lock_h: 24,
    play_weekday: 5, play_hour: 18, play_duration_h: 30, market_close_before_h: 24,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.competitions().then((d) => setComps(d.competitions)); }, []);
  const grupos: string[] = comps.find((c) => c.competition === f.competition)?.grupos ?? [];
  const set = (k: string, v: any) => setF((s) => ({ ...s, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const lg = await api.create({ ...f, grupo: f.grupo || grupos[0] || null });
      onDone(lg.id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit}>
      <h1 style={{ margin: "4px 2px 16px" }}>Nueva liga</h1>

      <div className="card card--pad">
        <label className="field">
          <span className="field__label">Nombre de la liga</span>
          <input className="input" value={f.name} required placeholder="La liga del grupo"
            onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Tu nombre de mánager</span>
          <input className="input" value={f.manager_name} placeholder="Pau"
            onChange={(e) => set("manager_name", e.target.value)} />
        </label>
        <label className="field" style={{ marginBottom: grupos.length > 1 ? 14 : 0 }}>
          <span className="field__label">Competición</span>
          <select className="select" value={f.competition} required
            onChange={(e) => { set("competition", e.target.value); set("grupo", ""); }}>
            <option value="" disabled>Elige competición…</option>
            {comps.map((c) => <option key={c.competition} value={c.competition}>{c.competition}</option>)}
          </select>
        </label>
        {grupos.length > 1 && (
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Grupo (conferencia)</span>
            <select className="select" value={f.grupo} required
              onChange={(e) => set("grupo", e.target.value)}>
              <option value="" disabled>Elige grupo…</option>
              {grupos.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </label>
        )}
      </div>

      <Section>Mercado</Section>
      <div className="card card--pad">
        <div className="grid2">
          <label className="field">
            <span className="field__label">Abre a las</span>
            <select className="select" value={f.market_hour}
              onChange={(e) => set("market_hour", Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) =>
                <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Duración</span>
            <select className="select" value={f.market_duration_h}
              onChange={(e) => set("market_duration_h", Number(e.target.value))}>
              {[6, 12, 24, 48, 72].map((h) => <option key={h} value={h}>{h} h</option>)}
            </select>
          </label>
        </div>
        <div className="grid2">
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Jugadores por tanda</span>
            <select className="select" value={f.market_size}
              onChange={(e) => set("market_size", Number(e.target.value))}>
              {[6, 8, 10, 12, 16, 20].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Plantilla inicial</span>
            <select className="select" value={f.initial_squad}
              onChange={(e) => set("initial_squad", Number(e.target.value))}>
              {[0, 3, 5, 7].map((n) => <option key={n} value={n}>{n} jugadores</option>)}
            </select>
          </label>
        </div>
        <p className="hint" style={{ margin: "12px 0 0" }}>
          Sale una <b>tanda nueva cada día</b> a las {String(f.market_hour).padStart(2, "0")}:00.
          La primera, nada más crear la liga.
        </p>
      </div>

      <Section>Jornada</Section>
      <div className="card card--pad">
        <div className="grid2">
          <label className="field">
            <span className="field__label">Se juega el</span>
            <select className="select" value={f.play_weekday}
              onChange={(e) => set("play_weekday", Number(e.target.value))}>
              {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Primer partido</span>
            <select className="select" value={f.play_hour}
              onChange={(e) => set("play_hour", Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) =>
                <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select>
          </label>
        </div>
        <div className="grid2">
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">El mercado cierra</span>
            <select className="select" value={f.market_close_before_h}
              onChange={(e) => set("market_close_before_h", Number(e.target.value))}>
              {[6, 12, 24, 48].map((h) => <option key={h} value={h}>{h} h antes</option>)}
            </select>
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Dura la jornada</span>
            <select className="select" value={f.play_duration_h}
              onChange={(e) => set("play_duration_h", Number(e.target.value))}>
              {[24, 30, 48, 72].map((h) => <option key={h} value={h}>{h} h</option>)}
            </select>
          </label>
        </div>
        <p className="hint" style={{ margin: "12px 0 0" }}>
          El mercado cierra {f.market_close_before_h} h antes del primer partido; el quinteto,
          al empezar la jornada. Mientras se juega no se toca nada, y se puntúa sola al acabar.
        </p>
      </div>

      <Section>Reglas</Section>
      <div className="card card--pad">
        <div className="grid2">
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Presupuesto</span>
            <select className="select" value={f.budget}
              onChange={(e) => set("budget", Number(e.target.value))}>
              {[80, 100, 150, 200].map((n) => <option key={n} value={n}>{n} M€</option>)}
            </select>
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Plantilla máxima</span>
            <select className="select" value={f.squad_size}
              onChange={(e) => set("squad_size", Number(e.target.value))}>
              {[8, 10, 12, 15].map((n) => <option key={n} value={n}>{n} jugadores</option>)}
            </select>
          </label>
        </div>
        <p className="hint" style={{ margin: "12px 0 0" }}>
          Sacas un <b>quinteto titular</b>. Cada uno suma sus <b>puntos fantasy</b>: su
          valoración del partido más un bonus si su equipo gana.
        </p>
      </div>

      <Section>Cláusulas</Section>
      <div className="card card--pad">
        <div className="grid2">
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Cláusula = valor ×</span>
            <select className="select" value={f.clause_factor}
              onChange={(e) => set("clause_factor", Number(e.target.value))}>
              {[1.5, 2, 2.5, 3, 4].map((n) => <option key={n} value={n}>×{n}</option>)}
            </select>
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Blindaje al fichar</span>
            <select className="select" value={f.clause_lock_h}
              onChange={(e) => set("clause_lock_h", Number(e.target.value))}>
              {[0, 12, 24, 48, 72].map((n) =>
                <option key={n} value={n}>{n === 0 ? "Sin blindaje" : `${n} h`}</option>)}
            </select>
          </label>
        </div>
        <p className="hint" style={{ margin: "12px 0 0" }}>
          Otro mánager puede llevarse a tu jugador pagando su cláusula, y ese dinero es para ti.
          Puedes subirla pagando un 25 % de la subida.
        </p>
      </div>

      {err && <div className="formerr" style={{ marginTop: 16 }}><IconAlert size={17} />{err}</div>}
      <button className="btn btn--block btn--lg" style={{ marginTop: 18 }} disabled={busy || !f.competition}>
        {busy ? <span className="spinner" /> : "Crear liga"}
      </button>
    </form>
  );
}

/* ------------------------------------------------------------- unirse */
function JoinLeague({ onDone, inicial, onUsada }: {
  onDone: (id: number) => void; inicial?: string | null; onUsada?: () => void;
}) {
  const [code, setCode] = useState(inicial ?? "");
  const [manager, setManager] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const lg = await api.join(code.trim().toUpperCase(), manager);
      onUsada?.();
      onDone(lg.id);
    }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit}>
      <h1 style={{ margin: "4px 2px 16px" }}>Unirme a una liga</h1>
      <div className="card card--pad">
        <label className="field">
          <span className="field__label">Código de invitación</span>
          <input className="input num" value={code} required placeholder="ABC123" maxLength={6}
            autoCapitalize="characters" autoCorrect="off" spellCheck={false}
            style={{ textTransform: "uppercase", letterSpacing: "0.28em", fontWeight: 800,
              textAlign: "center", fontSize: 20 }}
            onChange={(e) => setCode(e.target.value)} />
        </label>
        <label className="field" style={{ marginBottom: 0 }}>
          <span className="field__label">Tu nombre de mánager</span>
          <input className="input" value={manager} placeholder="Pau"
            onChange={(e) => setManager(e.target.value)} />
        </label>
      </div>
      {err && <div className="formerr" style={{ marginTop: 16 }}><IconAlert size={17} />{err}</div>}
      <button className="btn btn--block btn--lg" style={{ marginTop: 18 }} disabled={busy || code.length < 4}>
        {busy ? <span className="spinner" /> : "Unirme"}
      </button>
    </form>
  );
}


/* ------------------------------------------------ enlace de recuperación */
/**
 * Para cuando alguien pierde la contraseña y el correo automático no está configurado
 * (o no le llega): el administrador genera el enlace aquí y se lo pasa por donde sea.
 */
function ResetLinkTool() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [mins, setMins] = useState(30);
  const [err, setErr] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  async function generar(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setLink(null); setBusy(true);
    try {
      const r = await api.adminResetLink(email.trim());
      setLink(r.link); setMins(r.minutes); setCopiado(false);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <form className="card card--pad" onSubmit={generar}>
      <span className="field__label">Recuperar la contraseña de alguien</span>
      <p className="hint" style={{ margin: "0 0 10px" }}>
        Genera un enlace de un solo uso y pásaselo. Caduca en {mins} minutos.
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <input className="input" type="email" value={email} required placeholder="su@email.com"
          inputMode="email" onChange={(e) => setEmail(e.target.value)} />
        <button className="btn" disabled={busy || !email.trim()}>
          {busy ? <span className="spinner" /> : "Generar"}
        </button>
      </div>
      {err && <div className="formerr" style={{ marginTop: 12 }}><IconAlert size={17} />{err}</div>}
      {link && (
        <div className="resetlink">
          <code>{link}</code>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => {
            navigator.clipboard?.writeText(link);
            setCopiado(true);
          }}>{copiado ? "Copiado" : "Copiar"}</button>
        </div>
      )}
    </form>
  );
}


/* ------------------------------------------------- avisos en el movil */
function Avisos() {
  const [estado, setEstado] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { estadoPush().then(setEstado); }, []);

  async function alternar() {
    setBusy(true);
    try {
      if (estado === "activado") { await desactivarPush(); setEstado("desactivado"); }
      else setEstado(await activarPush());
    } finally { setBusy(false); }
  }

  if (!estado || estado === "no-soportado") return null;
  const texto: Record<string, string> = {
    activado: "Recibirás un aviso cuando te clausulen a alguien, pierdas una puja o se puntúe la jornada.",
    desactivado: "Actívalos y te avisamos aunque tengas la app cerrada.",
    instalar: "Para recibir avisos en el iPhone, añade la app a la pantalla de inicio (Compartir → Añadir a pantalla de inicio) y ábrela desde su icono.",
    bloqueado: "Los tienes bloqueados en el navegador. Se cambia en los ajustes del teléfono, en las notificaciones de PiFantasy.",
  };

  return (
    <div className="card card--pad" style={{ marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ color: estado === "activado" ? "var(--pos)" : "var(--text-3)" }}>
          <IconBell size={19} />
        </span>
        <span className="field__label" style={{ flex: 1, margin: 0 }}>Avisos en el móvil</span>
        {(estado === "activado" || estado === "desactivado") && (
          <button className={"btn btn--sm " + (estado === "activado" ? "btn--quiet" : "")}
            disabled={busy} onClick={alternar}>
            {busy ? <span className="spinner" /> : estado === "activado" ? "Desactivar" : "Activar"}
          </button>
        )}
      </div>
      <p className="hint" style={{ margin: "8px 0 0" }}>{texto[estado]}</p>
    </div>
  );
}
