import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { HalfCourtBg } from "../components/Iso";

const photo = (c: string | null) => (c ? `https://imagenes.feb.es/Foto.aspx?c=${c}` : "");
const hideImg = (e: any) => ((e.target as HTMLImageElement).style.visibility = "hidden");
const first = (n: string) => (n.includes(",") ? n.split(",")[0] : n).trim();

function Trend({ v }: { v: number }) {
  if (v > 0.4) return <span className="trend up">▲ {v.toFixed(1)}</span>;
  if (v < -0.4) return <span className="trend down">▼ {Math.abs(v).toFixed(1)}</span>;
  return <span className="trend flat">◆</span>;
}

const POS = [
  { left: "50%", top: "80%" }, { left: "19%", top: "60%" }, { left: "81%", top: "60%" },
  { left: "33%", top: "39%" }, { left: "66%", top: "27%" },
];

export default function FantasyLeague() {
  const { id } = useParams();
  const lid = Number(id);
  const nav = useNavigate();
  const { user } = useAuth();
  const [tab, setTab] = useState<"clasif" | "mercado" | "plantilla">("plantilla");
  const inited = useRef(false);
  const [data, setData] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [copied, setCopied] = useState(false);

  async function load() { setData(await api.fantasyLeague(lid)); }
  async function loadMarket() { setMarket(await api.fantasyMarket(lid)); }
  useEffect(() => { load(); }, [lid]);
  // al entrar por primera vez, si aún no tienes plantilla, lo primero es elegir jugadores
  useEffect(() => {
    if (data && !inited.current) {
      inited.current = true;
      if ((data.my_squad?.length ?? 0) === 0 && data.my_member_id) setTab("mercado");
    }
  }, [data]);
  useEffect(() => { if (tab === "mercado" && !market) loadMarket(); }, [tab]);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 2200); return () => clearTimeout(t); }, [msg]);

  if (!data) return <div className="fantasy-app"><div className="fa-col"><div className="fa-empty">Cargando liga…</div></div></div>;
  const lg = data.league;
  const squad = (data.my_squad as any[]) ?? [];
  const starters = squad.filter((p) => p.starter);
  const bench = squad.filter((p) => !p.starter);
  const done = lg.current_jornada >= lg.max_jornada;

  async function act(fn: () => Promise<any>, note?: string) {
    setBusy(true);
    try { await fn(); await load(); if (market) await loadMarket(); if (note) setMsg(note); }
    catch (e: any) { setMsg(e.message); }
    finally { setBusy(false); }
  }
  async function toggleStarter(pid: number, isStarter: boolean) {
    const ids = starters.map((p) => p.player_id);
    if (!isStarter && ids.length >= lg.lineup_size) { setMsg(`Máximo ${lg.lineup_size} titulares`); return; }
    const next = isStarter ? ids.filter((x) => x !== pid) : [...ids, pid];
    await act(() => api.fantasyLineup(lid, next));
  }

  return (
    <div className="fantasy-app">
      <div className="fa-topbar">
        <div className="fa-topbar-inner">
          <button className="fa-back" onClick={() => nav("/fantasy")}>← Mis ligas</button>
          <div className="fa-topline">
            <h1>{lg.name}</h1>
            {data.is_owner && (
              <button className="fa-btn" disabled={busy || done}
                onClick={() => act(() => api.fantasyAdvance(lid), done ? undefined : "¡Jornada puntuada!")}>
                {done ? "Temporada completa" : busy ? "…" : "▶ Avanzar"}
              </button>
            )}
          </div>
          <div className="fa-meta">
            <span className="fa-pill">{lg.competition}{lg.grupo ? ` · ${lg.grupo}` : ""}</span>
            <span className="fa-pill">Jornada <b>{lg.current_jornada}</b>/{lg.max_jornada}</span>
            {data.my_budget != null && <span className="fa-pill budget">💰 <b>{data.my_budget}</b> M€</span>}
            <span className="fa-pill code" onClick={() => { navigator.clipboard?.writeText(lg.join_code); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
              <b>{lg.join_code}</b> {copied ? "✓" : "⧉"}</span>
          </div>
        </div>
      </div>

      <div className="fa-col">
        {tab === "plantilla" && (
          <>
            <div className="formation">
              <HalfCourtBg />
              {POS.map((pos, i) => {
                const p = starters[i];
                return (
                  <div key={i} className={"token" + (p ? "" : " empty")} style={{ left: pos.left, top: pos.top }}>
                    {p ? <>
                      <img src={photo(p.feb_code)} onError={hideImg} />
                      <div className="tn">{first(p.name)}</div>
                      <div className="tp">{p.price} M€</div>
                    </> : <><img alt="" /><div className="tn" style={{ color: "var(--fa-muted)" }}>Vacío</div></>}
                  </div>
                );
              })}
            </div>
            <div className="fa-sec-title">Titulares · {starters.length}/{lg.lineup_size} <span style={{ color: "var(--fa-muted)", fontWeight: 600, textTransform: "none", letterSpacing: 0 }}>— solo estos puntúan</span></div>
            {starters.map((p) => <SquadCard key={p.player_id} p={p} busy={busy} onStar={() => toggleStarter(p.player_id, true)} onSell={() => act(() => api.fantasySell(lid, p.player_id))} />)}
            <div className="fa-sec-title">Banquillo · {bench.length}</div>
            {bench.length === 0 && <div className="fa-empty">Sin suplentes. Ficha más en el mercado.</div>}
            {bench.map((p) => <SquadCard key={p.player_id} p={p} busy={busy} onStar={() => toggleStarter(p.player_id, false)} onSell={() => act(() => api.fantasySell(lid, p.player_id))} />)}
            {squad.length === 0 && <div className="fa-empty">Aún no has fichado.<br />Ve al <b>Mercado</b> para formar tu equipo.</div>}
          </>
        )}

        {tab === "mercado" && (
          <>
            <div className="fa-search-row">
              <input className="fa-search" placeholder="🔍 Buscar jugador…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {market && <div className="fa-market-info"><span>🎲 {market.market.length} libres esta jornada · {squad.length}/{lg.squad_size} tuyos</span><span>Presupuesto: <b>{market.my_budget} M€</b></span></div>}
            {market && <p className="muted" style={{ fontSize: 11.5, margin: "-6px 2px 12px" }}>El mercado rota cada jornada. Cada jugador es exclusivo: si lo ficha alguien, desaparece para el resto.</p>}
            {!market ? <div className="fa-empty">Cargando mercado…</div> :
              market.market.filter((p: any) => p.name.toLowerCase().includes(q.toLowerCase())).map((p: any) => {
                const cant = p.owned || squad.length >= lg.squad_size || p.price > (market.my_budget ?? 0);
                return (
                  <div key={p.player_id} className="pcard">
                    <img className="ph" src={photo(p.feb_code)} onError={hideImg} />
                    <div className="mid">
                      <div className="nm">{first(p.name)}</div>
                      <div className="tm">{p.team}</div>
                      <div className="kv"><span>VAL <b>{p.val_avg}</b></span><span>+/- <b>{p.pm_avg > 0 ? "+" : ""}{p.pm_avg}</b></span></div>
                    </div>
                    <div className="right">
                      <div className="price">{p.price}<span className="cr">M€</span></div>
                      <Trend v={p.form - p.val_avg} />
                      {p.owned ? <span className="owned-tag">✓ Fichado</span> :
                        <button className="buy-btn" disabled={busy || cant} onClick={() => act(() => api.fantasyBuy(lid, p.player_id), "Fichado ✓")}>Fichar</button>}
                    </div>
                  </div>
                );
              })}
          </>
        )}

        {tab === "clasif" && (
          <>
            <Podium rows={data.standings.slice(0, 3)} />
            <div className="fa-sec-title">Clasificación</div>
            {data.standings.map((r: any) => (
              <div key={r.member_id} className={"rank-row" + (r.user_id === user?.id ? " me" : "")}>
                <div className="rk">{r.rank}</div>
                <div className="rn">{r.manager}<div className="rsub">{r.squad_count}/{lg.squad_size} jug · {r.squad_value} M€</div></div>
                <div className="rp">{r.total_points}</div>
              </div>
            ))}
          </>
        )}
      </div>

      {msg && <div className="fa-toast">{msg}</div>}

      <nav className="fa-tabbar">
        <button className={tab === "plantilla" ? "active" : ""} onClick={() => setTab("plantilla")}><span className="ic">👥</span>Equipo</button>
        <button className={tab === "mercado" ? "active" : ""} onClick={() => { setTab("mercado"); if (!market) loadMarket(); }}><span className="ic">🛒</span>Mercado</button>
        <button className={tab === "clasif" ? "active" : ""} onClick={() => setTab("clasif")}><span className="ic">🏆</span>Liga</button>
      </nav>
    </div>
  );
}

function SquadCard({ p, busy, onStar, onSell }: any) {
  return (
    <div className={"pcard" + (p.starter ? " starter" : "")}>
      <img className="ph" src={photo(p.feb_code)} onError={hideImg} />
      <div className="mid">
        <div className="nm">{first(p.name)}</div>
        <div className="tm">{p.team}</div>
        <div className="kv"><span>Compra <b>{p.buy_price}</b></span><span className={p.delta >= 0 ? "trend up" : "trend down"} style={{ fontSize: 11 }}>{p.delta >= 0 ? "▲" : "▼"} {Math.abs(p.delta)}</span></div>
      </div>
      <div className="right">
        <div className="price">{p.price}<span className="cr">M€</span></div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className={"star-btn" + (p.starter ? " on" : "")} disabled={busy} title={p.starter ? "Quitar de titulares" : "Poner de titular"} onClick={onStar}>★</button>
          <button className="sell-btn" disabled={busy} onClick={onSell}>Vender</button>
        </div>
      </div>
    </div>
  );
}

function Podium({ rows }: { rows: any[] }) {
  if (!rows.length) return null;
  const order = [rows[1], rows[0], rows[2]].filter(Boolean); // 2 - 1 - 3
  const cls: Record<number, string> = { 0: "p1", 1: "p2", 2: "p3" };
  return (
    <div className="podium">
      {order.map((r) => (
        <div key={r.member_id} className={"col " + cls[r.rank - 1]}>
          <div className="av">{r.manager?.[0]?.toUpperCase() ?? "?"}</div>
          <div className="nm">{r.manager}</div>
          <div className="pts">{r.total_points}</div>
          <div className="bar">{r.rank}º</div>
        </div>
      ))}
    </div>
  );
}
