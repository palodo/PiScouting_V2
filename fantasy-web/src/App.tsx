import { useEffect, useRef, useState } from "react";
import { api, getToken, photo, setToken, shortName } from "./api";
import { Ball, HalfCourt, Trend, fmtWhen, useCountdown } from "./ui";

const hideImg = (e: any) => ((e.target as HTMLImageElement).style.visibility = "hidden");
const DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

export default function App() {
  const [booted, setBooted] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [leagueId, setLeagueId] = useState<number | null>(null);

  useEffect(() => {
    if (!getToken()) { setBooted(true); return; }
    api.me().then(() => setAuthed(true)).catch(() => setToken(null)).finally(() => setBooted(true));
  }, []);

  if (!booted) return <div className="spin">Cargando…</div>;
  if (!authed) return <Login onAuth={() => setAuthed(true)} />;
  if (leagueId) return <League id={leagueId} onBack={() => setLeagueId(null)} />;
  return <Home onOpen={setLeagueId} onLogout={() => { setToken(null); setAuthed(false); }} />;
}

/* ------------------------------------------------------------------ login */
function Login({ onAuth }: { onAuth: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const r = mode === "login" ? await api.login(email.trim(), pass) : await api.signup(email.trim(), pass);
      setToken(r.token);
      onAuth();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="center-screen">
      <form onSubmit={submit} style={{ width: "100%", maxWidth: 380 }}>
        <div style={{ textAlign: "center", marginBottom: 26 }}>
          <Ball size={72} className="floaty" />
          <div className="logo" style={{ marginTop: 10 }}>Pi<span>Fantasy</span></div>
          <p className="dim" style={{ marginTop: 6, fontSize: 14 }}>Fantasy de baloncesto FEB</p>
        </div>
        <div className="seg">
          <button type="button" className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>Entrar</button>
          <button type="button" className={mode === "signup" ? "on" : ""} onClick={() => setMode("signup")}>Crear cuenta</button>
        </div>
        <label className="f"><span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label>
        <label className="f"><span>Contraseña</span>
          <input type="password" value={pass} onChange={(e) => setPass(e.target.value)} required
            autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
        {err && <div className="err">{err}</div>}
        <button className="btn block" disabled={busy}>{busy ? "…" : mode === "login" ? "Entrar" : "Crear cuenta"}</button>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ home */
function Home({ onOpen, onLogout }: { onOpen: (id: number) => void; onLogout: () => void }) {
  const [leagues, setLeagues] = useState<any[] | null>(null);
  const [view, setView] = useState<"list" | "create" | "join">("list");
  useEffect(() => { api.leagues().then(setLeagues).catch(() => setLeagues([])); }, []);

  return (
    <div className="app"><div className="col">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="logo" style={{ fontSize: 22 }}>Pi<span>Fantasy</span></div>
        <button className="back" onClick={onLogout}>Salir</button>
      </div>

      {view === "list" && <>
        <div className="hero">
          <Ball size={76} className="floaty" />
          <h1 style={{ fontSize: 27, marginTop: 12 }}>Tus ligas</h1>
          <p>Mercado con subastas, pujas a ciegas y precios que se mueven con la forma.</p>
        </div>
        {leagues === null ? <div className="spin">Cargando…</div> : <>
          {leagues.length === 0 && <div className="empty">Aún no estás en ninguna liga.<br />Crea una o únete con un código.</div>}
          {leagues.map((l) => (
            <button key={l.id} className="league-card" onClick={() => onOpen(l.id)}>
              <div className="league-top">
                <b>{l.name}</b>
                <span className={"tag" + (l.market_open ? " live" : "")}>{l.market_open ? "MERCADO ABIERTO" : l.competition}</span>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{l.grupo}</div>
              <div className="league-stats">
                <div><b>{l.member_points}</b><span>tus puntos</span></div>
                <div><b>{l.members}</b><span>mánagers</span></div>
                <div><b>J{l.current_jornada}</b><span>de {l.max_jornada}</span></div>
              </div>
            </button>
          ))}
        </>}
        <div className="grid2" style={{ marginTop: 18 }}>
          <button className="btn" onClick={() => setView("create")}>Crear liga</button>
          <button className="btn ghost" onClick={() => setView("join")}>Unirme</button>
        </div>
      </>}

      {view === "create" && <CreateLeague onBack={() => setView("list")} onDone={onOpen} />}
      {view === "join" && <JoinLeague onBack={() => setView("list")} onDone={onOpen} />}
    </div></div>
  );
}

function CreateLeague({ onBack, onDone }: { onBack: () => void; onDone: (id: number) => void }) {
  const [comps, setComps] = useState<any[]>([]);
  const [f, setF] = useState({
    name: "", manager_name: "", competition: "", grupo: "",
    market_weekday: 4, market_hour: 20, market_duration_h: 24, market_size: 10,
    budget: 100, squad_size: 10, lineup_size: 5, initial_squad: 5,
    clause_factor: 2.0, clause_lock_h: 24,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.competitions().then((d) => setComps(d.competitions)); }, []);
  const grupos = comps.find((c) => c.competition === f.competition)?.grupos ?? [];
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
      <button type="button" className="back" onClick={onBack}>‹ Volver</button>
      <h1 style={{ fontSize: 24, margin: "12px 0 16px" }}>Nueva liga</h1>

      <div className="panel">
        <label className="f"><span>Nombre de la liga</span>
          <input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="La liga del grupo" required /></label>
        <label className="f"><span>Tu nombre de mánager</span>
          <input value={f.manager_name} onChange={(e) => set("manager_name", e.target.value)} placeholder="Pau" /></label>
        <label className="f"><span>Competición</span>
          <select value={f.competition} onChange={(e) => { set("competition", e.target.value); set("grupo", ""); }} required>
            <option value="" disabled>Elige competición…</option>
            {comps.map((c) => <option key={c.competition} value={c.competition}>{c.competition}</option>)}
          </select></label>
        {grupos.length > 1 && (
          <label className="f"><span>Grupo (conferencia)</span>
            <select value={f.grupo} onChange={(e) => set("grupo", e.target.value)} required>
              <option value="" disabled>Elige grupo…</option>
              {grupos.map((g: string) => <option key={g} value={g}>{g}</option>)}
            </select></label>
        )}
      </div>

      <div className="sec">🛒 Mercado<div className="rest" /></div>
      <div className="panel">
        <label className="f"><span>Día que abre el mercado</span>
          <div className="chips">
            {DAYS.map((d, i) => (
              <button type="button" key={d} className={"chip" + (f.market_weekday === i ? " on" : "")}
                onClick={() => set("market_weekday", i)}>{d.slice(0, 3)}</button>
            ))}
          </div>
        </label>
        <div className="grid2">
          <label className="f"><span>Hora (peninsular)</span>
            <select value={f.market_hour} onChange={(e) => set("market_hour", Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select></label>
          <label className="f"><span>Duración</span>
            <select value={f.market_duration_h} onChange={(e) => set("market_duration_h", Number(e.target.value))}>
              {[6, 12, 24, 48, 72].map((h) => <option key={h} value={h}>{h} h</option>)}
            </select></label>
        </div>
        <div className="grid2">
          <label className="f"><span>Jugadores por tanda</span>
            <select value={f.market_size} onChange={(e) => set("market_size", Number(e.target.value))}>
              {[6, 8, 10, 12, 16, 20].map((n) => <option key={n} value={n}>{n}</option>)}
            </select></label>
          <label className="f"><span>Plantilla inicial</span>
            <select value={f.initial_squad} onChange={(e) => set("initial_squad", Number(e.target.value))}>
              {[0, 3, 5, 7].map((n) => <option key={n} value={n}>{n} jugadores</option>)}
            </select></label>
        </div>
        <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
          El mercado abre cada <b className="dim">{DAYS[f.market_weekday].toLowerCase()}</b> a las{" "}
          <b className="dim">{String(f.market_hour).padStart(2, "0")}:00</b> durante {f.market_duration_h} h.
          El primero se abre nada más crear la liga.
        </p>
      </div>

      <div className="sec">⚙️ Reglas<div className="rest" /></div>
      <div className="panel">
        <div className="grid2">
          <label className="f"><span>Presupuesto</span>
            <select value={f.budget} onChange={(e) => set("budget", Number(e.target.value))}>
              {[80, 100, 150, 200].map((n) => <option key={n} value={n}>{n} M€</option>)}
            </select></label>
          <label className="f"><span>Plantilla máx.</span>
            <select value={f.squad_size} onChange={(e) => set("squad_size", Number(e.target.value))}>
              {[8, 10, 12, 15].map((n) => <option key={n} value={n}>{n}</option>)}
            </select></label>
        </div>
        <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
          Alinearás 5 titulares. Puntúan por su valoración + bonus si su equipo gana.
        </p>
      </div>

      <div className="sec">💥 Cláusulas<div className="rest" /></div>
      <div className="panel">
        <div className="grid2">
          <label className="f"><span>Cláusula = valor ×</span>
            <select value={f.clause_factor} onChange={(e) => set("clause_factor", Number(e.target.value))}>
              {[1.5, 2, 2.5, 3, 4].map((n) => <option key={n} value={n}>×{n}</option>)}
            </select></label>
          <label className="f"><span>Blindaje al fichar</span>
            <select value={f.clause_lock_h} onChange={(e) => set("clause_lock_h", Number(e.target.value))}>
              {[0, 12, 24, 48, 72].map((n) => <option key={n} value={n}>{n === 0 ? "Sin blindaje" : `${n} h`}</option>)}
            </select></label>
        </div>
        <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
          Otro mánager puede llevarse a tu jugador pagando su cláusula (el dinero es para ti).
          Puedes subirla pagando un 25% de la subida.
        </p>
      </div>

      {err && <div className="err">{err}</div>}
      <button className="btn block" disabled={busy || !f.competition}>{busy ? "Creando…" : "Crear liga"}</button>
    </form>
  );
}

function JoinLeague({ onBack, onDone }: { onBack: () => void; onDone: (id: number) => void }) {
  const [code, setCode] = useState("");
  const [manager, setManager] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try { const lg = await api.join(code.trim().toUpperCase(), manager); onDone(lg.id); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit}>
      <button type="button" className="back" onClick={onBack}>‹ Volver</button>
      <h1 style={{ fontSize: 24, margin: "12px 0 16px" }}>Unirme a una liga</h1>
      <div className="panel">
        <label className="f"><span>Código de invitación</span>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="ABC123" required
            style={{ textTransform: "uppercase", letterSpacing: "0.2em", fontWeight: 800, textAlign: "center" }} /></label>
        <label className="f"><span>Tu nombre de mánager</span>
          <input value={manager} onChange={(e) => setManager(e.target.value)} placeholder="Pau" /></label>
      </div>
      {err && <div className="err">{err}</div>}
      <button className="btn block" disabled={busy}>{busy ? "…" : "Unirme"}</button>
    </form>
  );
}

/* ------------------------------------------------------------------ liga */
const POS = [{ l: "50%", t: "78%" }, { l: "16%", t: "58%" }, { l: "84%", t: "58%" }, { l: "31%", t: "34%" }, { l: "68%", t: "24%" }];

function League({ id, onBack }: { id: number; onBack: () => void }) {
  const [tab, setTab] = useState<"equipo" | "mercado" | "liga" | "feed">("equipo");
  const [data, setData] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [bidFor, setBidFor] = useState<any>(null);
  const [playerFor, setPlayerFor] = useState<number | null>(null);
  const [rivalFor, setRivalFor] = useState<any>(null);
  const inited = useRef(false);

  async function load() { const d = await api.league(id); setData(d); return d; }
  async function loadMarket() { const m = await api.market(id); setMarket(m); return m; }

  useEffect(() => {
    load().then((d) => {
      if (inited.current) return;
      inited.current = true;
      if (d.league.market_open) { setTab("mercado"); loadMarket(); }
    });
  }, [id]);
  // al cambiar de pestaña refrescamos: la liga es en vivo (nuevos mánagers, fichajes, cláusulas)
  useEffect(() => { load(); if (tab === "mercado") loadMarket(); }, [tab]);
  useEffect(() => {
    if (tab !== "mercado" || !data?.league?.market_open) return;
    const t = setInterval(() => { loadMarket(); load(); }, 20000);
    return () => clearInterval(t);
  }, [tab, data?.league?.market_open]);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 2400); return () => clearTimeout(t); }, [msg]);

  const closes = useCountdown(market?.closes_at ?? data?.league?.market_closes_at ?? null);
  const opens = useCountdown(data?.league?.market_opens_at ?? null);

  if (!data) return <div className="spin">Cargando liga…</div>;
  const lg = data.league;
  const squad: any[] = data.my_squad ?? [];
  const starters = squad.filter((p) => p.starter);
  const bench = squad.filter((p) => !p.starter);
  const done = lg.current_jornada >= lg.max_jornada;

  async function act(fn: () => Promise<any>, note?: string) {
    setBusy(true);
    try { await fn(); await load(); if (market || tab === "mercado") await loadMarket(); if (note) setMsg(note); }
    catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }
  function toggleStarter(pid: number, isStarter: boolean) {
    const ids = starters.map((p) => p.player_id);
    if (!isStarter && ids.length >= lg.lineup_size) { setMsg(`Máximo ${lg.lineup_size} titulares`); return; }
    act(() => api.lineup(id, isStarter ? ids.filter((x) => x !== pid) : [...ids, pid]));
  }

  return (
    <div className="app">
      <div className="topbar"><div className="topbar-in">
        <button className="back" onClick={onBack}>‹ Mis ligas</button>
        <div className="title-row">
          <h1>{lg.name}</h1>
          {data.is_owner && (
            <button className="btn sm" disabled={busy || done}
              onClick={() => act(() => api.advance(id), "¡Jornada puntuada!")}>
              {done ? "Fin" : "▶ Jornada"}
            </button>
          )}
        </div>
        <div className="pills">
          <span className={"pill " + (lg.market_open ? "live" : "shut")}>
            {lg.market_open ? <>🟢 Mercado <b>{closes}</b></> : <>🔴 Abre en <b>{opens ?? "—"}</b></>}
          </span>
          <span className="pill">J <b>{lg.current_jornada}</b>/{lg.max_jornada}</span>
          {data.my_budget != null && <span className="pill money">💰 <b>{data.my_budget}</b> M€</span>}
          <span className="pill tap" onClick={() => { navigator.clipboard?.writeText(lg.join_code); setMsg("Código copiado"); }}>
            <b>{lg.join_code}</b> ⧉
          </span>
        </div>
      </div></div>

      <div className="col">
        {tab === "equipo" && <>
          <div className="court">
            <HalfCourt />
            {POS.map((p, i) => {
              const pl = starters[i];
              return (
                <div key={i} className={"tok" + (pl ? "" : " empty") + (pl?.departed ? " gone" : "")}
                  style={{ left: p.l, top: p.t }}
                  title={pl?.departed ? "Fichó por otro equipo: no puntúa" : undefined}>
                  <img src={pl ? photo(pl.feb_code) : ""} onError={hideImg} alt="" />
                  <div className="n">{pl ? shortName(pl.name) : "Libre"}</div>
                  {pl && <div className="p">{pl.departed ? "no puntúa" : `${pl.price} M€`}</div>}
                </div>
              );
            })}
          </div>
          {squad.some((p: any) => p.departed) && (() => {
            const idos = squad.filter((p: any) => p.departed);
            const alineados = idos.filter((p: any) => p.starter);
            return (
              <div className="alert">
                <b>{idos.length === 1 ? "Un jugador de tu plantilla ha fichado por otro equipo"
                  : `${idos.length} jugadores de tu plantilla han fichado por otro equipo`}</b>
                <span>
                  {alineados.length > 0
                    ? `Tienes ${alineados.length === 1 ? "a uno" : `a ${alineados.length}`} en el once y `
                      + `${alineados.length === 1 ? "sumará" : "sumarán"} 0 puntos esta jornada. Cámbia${alineados.length === 1 ? "lo" : "los"} o vénde${alineados.length === 1 ? "lo" : "los"}.`
                    : "Ocupan sitio en la plantilla pero ya no puntúan. Véndelos para hacer hueco."}
                </span>
              </div>
            );
          })()}
          <div className="sec">Titulares · {starters.length}/{lg.lineup_size}<div className="rest" /></div>
          {starters.map((p) => <SquadCard key={p.player_id} p={p} busy={busy}
            onOpen={() => setPlayerFor(p.player_id)}
            onStar={() => toggleStarter(p.player_id, true)}
            onSell={() => act(() => api.sell(id, p.player_id), "Vendido")} />)}
          <div className="sec">Banquillo · {bench.length}<div className="rest" /></div>
          {bench.length === 0 && <div className="empty">Sin suplentes.</div>}
          {bench.map((p) => <SquadCard key={p.player_id} p={p} busy={busy}
            onOpen={() => setPlayerFor(p.player_id)}
            onStar={() => toggleStarter(p.player_id, false)}
            onSell={() => act(() => api.sell(id, p.player_id), "Vendido")} />)}
        </>}

        {tab === "mercado" && <>
          <div className={"market-head" + (lg.market_open ? "" : " closed")}>
            <div className="lbl">{lg.market_open ? "Mercado abierto · cierra en" : "Mercado cerrado · abre en"}</div>
            <div className="countdown">{lg.market_open ? closes : (opens ?? "—")}</div>
            <small>
              {lg.market_open
                ? `${market?.listings?.length ?? 0} jugadores a subasta · gana la puja más alta`
                : `Próxima apertura: ${fmtWhen(lg.market_opens_at)} · ${lg.market_size} jugadores`}
            </small>
            {data.is_owner && (
              <div style={{ marginTop: 12 }}>
                {lg.market_open
                  ? <button className="btn sm ghost" disabled={busy} onClick={() => act(() => api.closeMarket(id), "Mercado cerrado y pujas resueltas")}>Cerrar ya y resolver</button>
                  : <button className="btn sm ghost" disabled={busy} onClick={() => act(() => api.openMarket(id), "Mercado abierto")}>Abrir ya</button>}
              </div>
            )}
          </div>

          {market && market.committed > 0 && (
            <p className="muted" style={{ fontSize: 12, margin: "-4px 4px 12px" }}>
              Comprometido en pujas: <b className="gold">{market.committed} M€</b> · libre para pujar:{" "}
              <b className="gold">{Math.round((market.my_budget - market.committed) * 10) / 10} M€</b>
            </p>
          )}

          {!lg.market_open ? <div className="empty">El mercado está cerrado.<br />Vuelve cuando abra para pujar.</div>
            : !market ? <div className="spin">Cargando mercado…</div>
              : market.listings.map((l: any) => (
                <div key={l.listing_id} className={"pcard tapable" + (l.my_bid ? " mine" : "")}
                  onClick={() => setPlayerFor(l.player_id)}>
                  <img className="ph" src={photo(l.feb_code)} onError={hideImg} alt="" />
                  <div className="mid">
                    <div className="nm">{shortName(l.name)}</div>
                    <div className="tm">{l.team}</div>
                    <div className="kv">
                      <span>VAL <b>{l.val_avg}</b></span>
                      <span>+/- <b>{l.pm_avg > 0 ? "+" : ""}{l.pm_avg}</b></span>
                      {l.bids > 0 && <span className="bidcount">🔨 {l.bids}</span>}
                    </div>
                  </div>
                  <div className="right">
                    <div className="price tnum">{l.price}<span className="u">M€</span></div>
                    <Trend v={l.form - l.val_avg} />
                    {l.my_bid
                      ? <span className="mybid">Tu puja {l.my_bid}</span>
                      : null}
                    <button className="btn sm" disabled={busy}
                      onClick={(e) => { e.stopPropagation(); setBidFor(l); }}>
                      {l.my_bid ? "Cambiar" : "Pujar"}
                    </button>
                  </div>
                </div>
              ))}
        </>}

        {tab === "liga" && <>
          <div className="sec">Clasificación<div className="rest" /></div>
          <p className="muted" style={{ fontSize: 12, margin: "-4px 4px 12px" }}>
            Toca un mánager para ver su plantilla y sus cláusulas 💥
          </p>
          {data.standings.map((r: any) => (
            <div key={r.member_id} className={"rank tapable" + (r.member_id === data.my_member_id ? " me" : "")}
              onClick={() => api.memberSquad(id, r.member_id).then(setRivalFor)}>
              <div className="pos">{r.rank}</div>
              <div className="who">
                <b>{r.manager}</b>
                <small>{r.squad_count}/{lg.squad_size} jugadores · {r.squad_value} M€ · {r.budget_remaining} M€ libres</small>
              </div>
              <div className="pts tnum">{r.total_points}</div>
            </div>
          ))}
        </>}

        {tab === "feed" && <>
          <div className="sec">Actividad<div className="rest" /></div>
          {(data.feed ?? []).length === 0 && <div className="empty">Sin movimientos todavía.</div>}
          {(data.feed ?? []).map((e: any) => (
            <div key={e.id} className="ev">
              <span style={{ flex: 1 }}>{e.text}</span>
              <small>{new Date(e.at).toLocaleDateString("es-ES", { day: "2-digit", month: "short" })}</small>
            </div>
          ))}
        </>}
      </div>

      {msg && <div className="toast">{msg}</div>}

      {playerFor && (
        <PlayerSheet leagueId={id} playerId={playerFor} league={lg} busy={busy}
          myMemberId={data.my_member_id} freeBudget={(data.my_budget ?? 0) - (data.my_committed ?? 0)}
          onClose={() => setPlayerFor(null)}
          onClause={async (pid: number) => { setPlayerFor(null); await act(() => api.payClause(id, pid), "💥 ¡Clausulazo!"); }}
          onRaise={async (pid: number, v: number) => { setPlayerFor(null); await act(() => api.raiseClause(id, pid, v), "Cláusula subida"); }} />
      )}

      {rivalFor && (
        <div className="overlay" onClick={() => setRivalFor(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3>{rivalFor.manager}</h3>
            <div className="dim" style={{ fontSize: 12.5, marginBottom: 14 }}>
              {rivalFor.points} pts · {rivalFor.budget} M€ libres · toca un jugador para su ficha
            </div>
            <div style={{ maxHeight: "56vh", overflowY: "auto" }}>
              {rivalFor.squad.map((p: any) => (
                <div key={p.player_id} className="pcard tapable"
                  onClick={() => { setRivalFor(null); setPlayerFor(p.player_id); }}>
                  <img className="ph" src={photo(p.feb_code)} onError={hideImg} alt="" />
                  <div className="mid">
                    <div className="nm">{shortName(p.name)}</div>
                    <div className="tm">{p.team}</div>
                    <div className="kv"><span>VAL <b>{p.val_avg}</b></span><span>Valor <b>{p.price}</b></span></div>
                  </div>
                  <div className="right">
                    <div className="clause-tag">💥 {p.clause} M€</div>
                    {p.clause_locked && <span className="muted" style={{ fontSize: 10.5 }}>
                      🔒 {Math.floor(p.clause_lock_mins / 60)}h {p.clause_lock_mins % 60}m</span>}
                  </div>
                </div>
              ))}
            </div>
            <button className="btn ghost block" style={{ marginTop: 12 }} onClick={() => setRivalFor(null)}>Cerrar</button>
          </div>
        </div>
      )}

      {bidFor && (
        <BidSheet listing={bidFor} budget={(market?.my_budget ?? 0) - (market?.committed ?? 0) + (bidFor.my_bid ?? 0)}
          onClose={() => setBidFor(null)}
          onBid={async (amount) => { setBidFor(null); await act(() => api.bid(id, bidFor.listing_id, amount), `Puja de ${amount} M€ enviada`); }}
          onCancel={bidFor.my_bid ? async () => { setBidFor(null); await act(() => api.cancelBid(id, bidFor.listing_id), "Puja retirada"); } : undefined} />
      )}

      <nav className="tabbar">
        {([["equipo", "👥", "Equipo"], ["mercado", "🛒", "Mercado"], ["liga", "🏆", "Liga"], ["feed", "📰", "Actividad"]] as const).map(([k, i, l]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k as any)}>
            <span className="i">{i}</span>{l}
            {k === "mercado" && lg.market_open && tab !== "mercado" && <span className="dot" />}
          </button>
        ))}
      </nav>
    </div>
  );
}

function SquadCard({ p, busy, onStar, onSell, onOpen }: any) {
  const stop = (e: any, fn: () => void) => { e.stopPropagation(); fn(); };
  return (
    <div className={"pcard tapable" + (p.starter ? " starter" : "") + (p.departed ? " gone" : "")}
      onClick={onOpen}>
      <img className="ph" src={photo(p.feb_code)} onError={hideImg} alt="" />
      <div className="mid">
        <div className="nm">{shortName(p.name)}</div>
        <div className="tm">{p.team}</div>
        {p.departed
          ? <div className="gone-tag">Fichó por otro equipo · ya no puntúa</div>
          : <div className="kv">
              <span>VAL <b>{p.val_avg}</b></span>
              <span className={p.delta >= 0 ? "up" : "down"}>{p.delta >= 0 ? "▲" : "▼"} {Math.abs(p.delta)}</span>
              <span className="clause-mini">💥 {p.clause}{p.clause_locked ? " 🔒" : ""}</span>
            </div>}
      </div>
      <div className="right">
        <div className="price tnum">{p.price}<span className="u">M€</span></div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button className={"star" + (p.starter ? " on" : "")} disabled={busy || p.departed}
            onClick={(e) => stop(e, onStar)}
            title={p.departed ? "Ya no juega en tu liga: no puede ser titular"
              : p.starter ? "Quitar de titulares" : "Poner de titular"}>⭐</button>
          <button className="btn sm danger" disabled={busy} onClick={(e) => stop(e, onSell)}>Vender</button>
        </div>
      </div>
    </div>
  );
}

/* --------------------------- ficha completa del jugador --------------------------- */
function PlayerSheet({ leagueId, playerId, league, myMemberId, freeBudget, busy, onClose, onClause, onRaise }: any) {
  const [d, setD] = useState<any>(null);
  const [raising, setRaising] = useState(false);
  const [newClause, setNewClause] = useState(0);
  useEffect(() => { api.player(leagueId, playerId).then((x) => { setD(x); setNewClause(Math.round(((x.clause ?? 0) + 10) * 10) / 10); }); }, [playerId]);

  const mine = d && d.owner_member_id && d.owner_member_id === myMemberId;
  const rival = d && d.owner_member_id && d.owner_member_id !== myMemberId;
  const maxVal = d ? Math.max(...d.last.map((g: any) => Math.abs(g.val)), 1) : 1;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        {!d ? <div className="spin">Cargando ficha…</div> : <>
          <div style={{ display: "flex", gap: 13, alignItems: "center" }}>
            <img className="ph big" src={photo(d.feb_code)} onError={hideImg} alt="" />
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3>{shortName(d.name)}</h3>
              <div className="muted" style={{ fontSize: 12.5 }}>{d.team}</div>
              <div style={{ marginTop: 5, display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span className="pill money">💰 <b>{d.price}</b> M€</span>
                <span className="pill">{d.games} PJ · {d.wins}V-{d.losses}D</span>
              </div>
            </div>
          </div>

          <div className="statgrid">
            {[["PTS", d.avg.pts], ["REB", d.avg.reb], ["AST", d.avg.ast], ["VAL", d.avg.val]].map(([k, v]) => (
              <div key={k as string} className="stat big"><b>{v as number}</b><span>{k as string}</span></div>
            ))}
          </div>
          <div className="statgrid">
            {[["MIN", d.avg.min], ["ROB", d.avg.stl], ["TAP", d.avg.blk], ["PER", d.avg.tov],
              ["+/-", d.avg.pm], ["FLT", d.avg.pf]].map(([k, v]) => (
              <div key={k as string} className="stat"><b>{v as number}</b><span>{k as string}</span></div>
            ))}
          </div>
          <div className="statgrid">
            {[["T. campo", d.pct.fg], ["2P", d.pct.t2], ["3P", d.pct.t3], ["TL", d.pct.tl], ["TS%", d.pct.ts]].map(([k, v]) => (
              <div key={k as string} className="stat"><b>{v as number}%</b><span>{k as string}</span></div>
            ))}
          </div>

          <div className="sec" style={{ marginTop: 16 }}>Últimas jornadas<div className="rest" /></div>
          <div className="bars">
            {d.last.map((g: any, i: number) => (
              <div key={i} className="bar-col" title={`J${g.j}: ${g.val} val`}>
                <div className={"bar" + (g.won ? " win" : "")} style={{ height: `${Math.max(4, (Math.abs(g.val) / maxVal) * 46)}px` }} />
                <span>{g.val}</span>
              </div>
            ))}
          </div>

          <div className="sec" style={{ marginTop: 14 }}>Situación<div className="rest" /></div>
          {!d.owner && <p className="dim" style={{ margin: "0 0 12px", fontSize: 13.5 }}>Jugador libre — se puede fichar en el mercado.</p>}
          {d.owner && (
            <div className="clause-box">
              <div>
                <div className="muted" style={{ fontSize: 11.5, fontWeight: 800, letterSpacing: "0.08em" }}>
                  {mine ? "TU JUGADOR" : `DE ${String(d.owner).toUpperCase()}`}
                </div>
                <div style={{ fontSize: 21, fontWeight: 900, fontFamily: "var(--display)" }}>
                  💥 {d.clause} <span style={{ fontSize: 12, color: "var(--muted)" }}>M€ cláusula</span>
                </div>
                {d.clause_locked && <div className="muted" style={{ fontSize: 12 }}>
                  🔒 Blindado {Math.floor(d.clause_lock_mins / 60)}h {d.clause_lock_mins % 60}m</div>}
              </div>
            </div>
          )}

          {rival && (
            <button className="btn block" disabled={busy || d.clause_locked || d.clause > freeBudget}
              onClick={() => onClause(d.player_id)}>
              {d.clause_locked ? "Blindado" : d.clause > freeBudget ? `Te faltan ${Math.round((d.clause - freeBudget) * 10) / 10} M€` : `💥 Pagar cláusula · ${d.clause} M€`}
            </button>
          )}
          {mine && !raising && (
            <button className="btn ghost block" onClick={() => setRaising(true)}>🔒 Subir cláusula</button>
          )}
          {mine && raising && (
            <>
              <div className="bid-row">
                <button className="step" onClick={() => setNewClause((v) => Math.max(d.clause + 0.5, Math.round((v - 5) * 10) / 10))}>−</button>
                <input type="number" step="0.5" value={newClause} className="tnum"
                  onChange={(e) => setNewClause(Number(e.target.value))} />
                <button className="step" onClick={() => setNewClause((v) => Math.round((v + 5) * 10) / 10)}>+</button>
              </div>
              <p className="muted" style={{ fontSize: 12, margin: "6px 0 12px" }}>
                Subirla de {d.clause} a {newClause} M€ cuesta{" "}
                <b className="gold">{Math.round((newClause - d.clause) * league.clause_raise_cost * 10) / 10} M€</b>.
              </p>
              <button className="btn block" disabled={busy || newClause <= d.clause}
                onClick={() => onRaise(d.player_id, newClause)}>Confirmar subida</button>
            </>
          )}
          <button className="btn ghost block" style={{ marginTop: 9 }} onClick={onClose}>Cerrar</button>
        </>}
      </div>
    </div>
  );
}

function BidSheet({ listing, budget, onClose, onBid, onCancel }: {
  listing: any; budget: number; onClose: () => void;
  onBid: (amount: number) => void; onCancel?: () => void;
}) {
  const min = listing.price;
  const [amount, setAmount] = useState<number>(listing.my_bid ?? min);
  const max = Math.max(min, Math.round(budget * 10) / 10);
  const step = (d: number) => setAmount((a) => Math.min(max, Math.max(min, Math.round((a + d) * 10) / 10)));
  const valid = amount >= min && amount <= max + 1e-6;
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 4 }}>
          <img className="ph" src={photo(listing.feb_code)} onError={hideImg} alt="" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3>{shortName(listing.name)}</h3>
            <div className="muted" style={{ fontSize: 12 }}>{listing.team}</div>
            <div className="dim" style={{ fontSize: 12, marginTop: 3 }}>
              Salida <b className="gold">{min} M€</b> · {listing.bids} puja{listing.bids === 1 ? "" : "s"}
            </div>
          </div>
        </div>

        <div className="bid-row">
          <button className="step" onClick={() => step(-0.5)}>−</button>
          <input type="number" step="0.1" value={amount}
            onChange={(e) => setAmount(Number(e.target.value))} className="tnum" />
          <button className="step" onClick={() => step(0.5)}>+</button>
        </div>
        <div className="quick">
          {[0, 1, 3, 5].map((d) => (
            <button key={d} onClick={() => setAmount(Math.min(max, Math.round((min + d) * 10) / 10))}>
              {d === 0 ? "Mínimo" : `+${d}`}
            </button>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 12, margin: "8px 0 14px" }}>
          Puedes pujar hasta <b className="gold">{max} M€</b>. Las pujas son secretas: gana la más alta al cerrar.
        </p>
        <button className="btn block" disabled={!valid} onClick={() => onBid(amount)}>
          {listing.my_bid ? "Actualizar puja" : "Pujar"} · {amount} M€
        </button>
        {onCancel && <button className="btn block danger" style={{ marginTop: 9 }} onClick={onCancel}>Retirar puja</button>}
      </div>
    </div>
  );
}
