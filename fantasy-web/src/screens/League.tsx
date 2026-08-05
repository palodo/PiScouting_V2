/* ============================================================================
   Pantalla de una liga: equipo, mercado, clasificación y actividad.
   La lógica de datos es la misma de siempre (mismos endpoints); lo que cambia
   es cómo se presenta.
   ========================================================================== */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Me } from "../App";
import {
  IconActivity, IconAlert, IconArrowLeft, IconBolt, IconCheck, IconChevronLeft,
  IconChevronRight, IconClose, IconCopy, IconMarket, IconPlay, IconSquad,
  IconStar, IconStarOn, IconTrophy,
} from "../icons";
import { Delta, FeedRow, PlayerRow, fp } from "../parts";
import {
  Empty, HalfCourt, Loading, Photo, Section, Segmented, SkeletonList,
  fmtWhen, prettyName, useCountdown, useNow,
} from "../ui";
import { BidSheet, ManagerSheet, PlayerSheet } from "./sheets";

type Tab = "equipo" | "mercado" | "liga" | "feed";
const TABS: [Tab, (p: any) => any, string][] = [
  ["equipo", IconSquad, "Equipo"],
  ["mercado", IconMarket, "Mercado"],
  ["liga", IconTrophy, "Liga"],
  ["feed", IconActivity, "Actividad"],
];

/** Posiciones de los cinco titulares sobre la media pista. */
const SLOTS = [
  { left: "50%", top: "80%" }, { left: "17%", top: "63%" }, { left: "83%", top: "63%" },
  { left: "30%", top: "35%" }, { left: "70%", top: "31%" },
];

const r1 = (n: number) => Math.round(n * 10) / 10;

export default function League({ id, me, onBack }: { id: number; me: Me; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("equipo");
  const [data, setData] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [bidFor, setBidFor] = useState<any>(null);
  const [playerFor, setPlayerFor] = useState<number | null>(null);
  const [rivalFor, setRivalFor] = useState<any>(null);
  const [jr, setJr] = useState<any>(null);
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
  // al cambiar de pestaña refrescamos: la liga es en vivo (fichajes, cláusulas, nuevos mánagers)
  useEffect(() => { load(); if (tab === "mercado") loadMarket(); }, [tab]);
  useEffect(() => {
    if (tab !== "mercado" || !data?.league?.market_open) return;
    const t = setInterval(() => { loadMarket(); load(); }, 20000);
    return () => clearInterval(t);
  }, [tab, data?.league?.market_open]);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 2600); return () => clearTimeout(t); }, [msg]);
  useEffect(() => { setJr(data?.jornada_ranking ?? null); }, [data?.jornada_ranking]);

  const closes = useCountdown(market?.closes_at ?? data?.league?.market_closes_at ?? null);
  const opens = useCountdown(data?.league?.market_opens_at ?? null);

  if (!data) {
    return (
      <div className="shell">
        <header className="appbar"><div className="appbar__in appbar__in--flat">
          <div className="appbar__nav">
            <button className="linkbtn" onClick={onBack}><IconArrowLeft size={18} />Mis ligas</button>
          </div>
        </div></header>
        <main className="wrap"><Loading label="Cargando liga" /></main>
      </div>
    );
  }

  const lg = data.league;
  const squad: any[] = data.my_squad ?? [];
  const starters = squad.filter((p) => p.starter);
  const bench = squad.filter((p) => !p.starter);
  const done = lg.current_jornada >= lg.max_jornada;
  const admin = Boolean(data.is_owner || me.is_admin);
  const freeBudget = r1((data.my_budget ?? 0) - (data.my_committed ?? 0));

  async function act(fn: () => Promise<any>, note?: string) {
    setBusy(true);
    try {
      await fn();
      await load();
      if (market || tab === "mercado") await loadMarket();
      if (note) setMsg({ text: note });
    } catch (e: any) {
      setMsg({ text: e.message, bad: true });
    } finally { setBusy(false); }
  }

  function toggleStarter(pid: number, isStarter: boolean) {
    const ids = starters.map((p) => p.player_id);
    if (!isStarter && ids.length >= lg.lineup_size) {
      setMsg({ text: `Solo puedes alinear ${lg.lineup_size} titulares`, bad: true });
      return;
    }
    act(() => api.lineup(id, isStarter ? ids.filter((x) => x !== pid) : [...ids, pid]));
  }

  function copyCode() {
    navigator.clipboard?.writeText(lg.join_code);
    setMsg({ text: "Código copiado" });
  }

  return (
    <div className="shell">
      <header className="appbar">
        <div className="appbar__in">
          <div className="appbar__nav">
            <button className="linkbtn" onClick={onBack}><IconArrowLeft size={18} />Mis ligas</button>
            <span style={{ flex: 1 }} />
            {admin && (
              <button className="btn btn--sm btn--ghost" disabled={busy || done}
                onClick={() => act(async () => {
                  // puede responder ok:false si la jornada tiene partidos sin jugar
                  const r: any = await api.advance(id);
                  setMsg(r?.ok === false
                    ? { text: r.message, bad: true }
                    : { text: `Jornada ${r?.jornada ?? ""} puntuada` });
                })}>
                <IconPlay size={13} />{done ? "Temporada completa" : "Puntuar jornada"}
              </button>
            )}
          </div>

          <div className="appbar__title"><h1>{lg.name}</h1></div>

          <div className="metastrip">
            <div className={"meta" + (lg.market_open ? " meta--live" : "")}>
              <span className="meta__k">
                <span className={"livedot" + (lg.market_open ? "" : " livedot--off")} />
                {lg.market_open ? "Cierra en" : "Abre en"}
              </span>
              <span className="meta__v num">{lg.market_open ? closes : (opens ?? "—")}</span>
            </div>
            <div className="meta">
              <span className="meta__k">Jornada</span>
              <span className="meta__v num">{lg.current_jornada}<span className="muted">/{lg.max_jornada}</span></span>
            </div>
            {data.my_budget != null && (
              <div className="meta meta--money">
                <span className="meta__k">Saldo</span>
                <span className="meta__v num">{r1(data.my_budget)} M€</span>
              </div>
            )}
            <button className="meta" onClick={copyCode}>
              <span className="meta__k">Código</span>
              <span className="meta__v">{lg.join_code}<IconCopy size={13} /></span>
            </button>
          </div>
        </div>
      </header>

      <main className="wrap wrap--tabbed">
        {tab === "equipo" && (
          <TeamTab lg={lg} squad={squad} starters={starters} bench={bench} busy={busy}
            onOpen={setPlayerFor} onToggle={toggleStarter} />
        )}

        {tab === "mercado" && (
          <MarketTab lg={lg} market={market} admin={admin} busy={busy} closes={closes} opens={opens}
            onOpenPlayer={setPlayerFor} onBid={setBidFor}
            onForceOpen={() => act(() => api.openMarket(id), "Mercado abierto")}
            onForceClose={() => act(() => api.closeMarket(id), "Mercado cerrado y pujas resueltas")} />
        )}

        {tab === "liga" && (
          <TableTab data={data} lg={lg} jr={jr}
            onJornada={(j: number) => api.jornada(id, j).then(setJr).catch(() => {})}
            onManager={(mid: number) => api.memberSquad(id, mid).then(setRivalFor).catch(() => {})} />
        )}

        {tab === "feed" && (
          <>
            <Section>Actividad</Section>
            {(data.feed ?? []).length === 0
              ? <Empty icon={<IconActivity size={22} />} title="Sin movimientos todavía">
                  Aquí aparecerán los fichajes, los clausulazos y las jornadas puntuadas.
                </Empty>
              : <div className="tl">{data.feed.map((e: any) => <FeedRow key={e.id} e={e} />)}</div>}
          </>
        )}
      </main>

      {msg && (
        <div className="toast">
          <span className="toast__ico" style={msg.bad ? { color: "var(--neg)" } : undefined}>
            {msg.bad ? <IconAlert size={17} /> : <IconCheck size={17} />}
          </span>
          {msg.text}
        </div>
      )}

      {playerFor != null && (
        <PlayerSheet leagueId={id} playerId={playerFor} league={lg} busy={busy}
          myMemberId={data.my_member_id} freeBudget={freeBudget}
          onClose={() => setPlayerFor(null)}
          onClause={async (pid: number) => { setPlayerFor(null); await act(() => api.payClause(id, pid), "¡Clausulazo!"); }}
          onRaise={async (pid: number, v: number) => { setPlayerFor(null); await act(() => api.raiseClause(id, pid, v), "Cláusula subida"); }}
          onSell={async (pid: number) => { setPlayerFor(null); await act(() => api.sell(id, pid), "Jugador vendido"); }} />
      )}

      {rivalFor && (
        <ManagerSheet data={rivalFor} onClose={() => setRivalFor(null)}
          onPlayer={(pid) => { setRivalFor(null); setPlayerFor(pid); }} />
      )}

      {bidFor && (
        <BidSheet listing={bidFor} busy={busy}
          budget={(market?.my_budget ?? 0) - (market?.committed ?? 0) + (bidFor.my_bid ?? 0)}
          onClose={() => setBidFor(null)}
          onBid={async (amount) => { setBidFor(null); await act(() => api.bid(id, bidFor.listing_id, amount), `Puja de ${amount} M€ enviada`); }}
          onCancel={bidFor.my_bid
            ? async () => { setBidFor(null); await act(() => api.cancelBid(id, bidFor.listing_id), "Puja retirada"); }
            : undefined} />
      )}

      <nav className="tabbar">
        <div className="tabbar__in">
          {TABS.map(([k, Icon, label]) => (
            <button key={k} className={"tab" + (tab === k ? " is-on" : "")} onClick={() => setTab(k)}>
              <span className="tab__ico"><Icon size={21} strokeWidth={tab === k ? 2.1 : 1.7} /></span>
              {label}
              {k === "mercado" && lg.market_open && tab !== "mercado" && <span className="tab__badge" />}
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}

/* ------------------------------------------------------------------ equipo */
function TeamTab({ lg, squad, starters, bench, busy, onOpen, onToggle }: any) {
  const gone = squad.filter((p: any) => p.departed);
  const goneStarters = gone.filter((p: any) => p.starter);
  const lineupFp = r1(starters.reduce((a: number, p: any) => a + (p.departed ? 0 : fp(p)), 0));

  const StarBtn = ({ p }: { p: any }) => (
    <button className={"iconbtn" + (p.starter ? " is-on" : "")} disabled={busy || p.departed}
      title={p.departed ? "Ya no puntúa en esta conferencia"
        : p.starter ? "Quitar del once" : "Poner en el once"}
      onClick={(e) => { e.stopPropagation(); onToggle(p.player_id, p.starter); }}>
      {p.starter ? <IconStarOn size={19} /> : <IconStar size={19} />}
    </button>
  );

  return (
    <>
      <div className="court">
        <HalfCourt />
        {SLOTS.map((pos, i) => {
          const p = starters[i];
          return (
            <div key={i} style={pos as any}
              className={"tok" + (p ? "" : " tok--empty") + (p?.departed ? " tok--gone" : "")}>
              <Photo code={p?.feb_code} name={p?.name} variant="tok" />
              <span className="tok__tag">{p ? prettyName(p.name).split(" ").slice(-1)[0] : "Libre"}</span>
              {p && <span className="tok__sub num">{p.departed ? "0 PF" : `${fp(p).toFixed(1)} PF`}</span>}
            </div>
          );
        })}
      </div>

      {gone.length > 0 && (
        <div className="notice">
          <span className="notice__ico"><IconAlert size={18} /></span>
          <div>
            <b>{gone.length === 1
              ? "Un jugador tuyo ha fichado por otro equipo"
              : `${gone.length} jugadores tuyos han fichado por otro equipo`}</b>
            <span>{goneStarters.length === 1
              ? "Tienes a uno en el once y sumará 0 puntos: cámbialo o véndelo desde su ficha."
              : goneStarters.length > 1
                ? `Tienes a ${goneStarters.length} en el once y sumarán 0 puntos: cámbialos o véndelos desde su ficha.`
                : "Ocupan sitio en la plantilla pero ya no puntúan. Véndelos para hacer hueco."}</span>
          </div>
        </div>
      )}

      <Section right={`${starters.length}/${lg.lineup_size}`}>Once titular</Section>
      <div className="card card--pad" style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ color: "var(--accent)" }}><IconBolt size={20} strokeWidth={2} /></span>
        <div style={{ flex: 1 }}>
          <div className="muted" style={{ fontSize: "var(--fs-xs)", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Proyección por jornada
          </div>
          <div className="dim" style={{ fontSize: "var(--fs-sm)" }}>
            Puntos fantasy que suma tu once según su media
          </div>
        </div>
        <div className="num" style={{ fontFamily: "var(--display)", fontSize: "var(--fs-2xl)", fontWeight: 800 }}>
          {lineupFp}
        </div>
      </div>

      {starters.length === 0 && (
        <Empty icon={<IconSquad size={22} />} title="No has alineado a nadie">
          Marca con la estrella a {lg.lineup_size} jugadores de tu plantilla.
        </Empty>
      )}
      {starters.map((p: any) => (
        <PlayerRow key={p.player_id} p={p} onOpen={() => onOpen(p.player_id)}
          tone={p.departed ? "gone" : "starter"}
          right={<><Delta v={p.delta} /><StarBtn p={p} /></>} />
      ))}

      <Section right={String(bench.length)}>Banquillo</Section>
      {bench.length === 0 && (
        <Empty icon={<IconSquad size={22} />} title="Sin suplentes">
          Ficha jugadores en el mercado para tener recambios.
        </Empty>
      )}
      {bench.map((p: any) => (
        <PlayerRow key={p.player_id} p={p} onOpen={() => onOpen(p.player_id)}
          tone={p.departed ? "gone" : undefined}
          right={<><Delta v={p.delta} /><StarBtn p={p} /></>} />
      ))}
    </>
  );
}

/* ----------------------------------------------------------------- mercado */
function MarketTab({ lg, market, admin, busy, closes, opens, onOpenPlayer, onBid, onForceOpen, onForceClose }: any) {
  const now = useNow(5000);
  const from = market?.opens_at ?? lg.market_opens_at;
  const to = market?.closes_at ?? lg.market_closes_at;
  let pct = 0;
  if (lg.market_open && from && to) {
    const a = new Date(from).getTime(), b = new Date(to).getTime();
    pct = Math.min(100, Math.max(0, ((now - a) / (b - a)) * 100));
  }
  const committed = market?.committed ?? 0;
  const free = r1((market?.my_budget ?? 0) - committed);

  return (
    <>
      <div className={"mkt" + (lg.market_open ? "" : " mkt--closed")}>
        <div className="mkt__k">
          <span className={"livedot" + (lg.market_open ? "" : " livedot--off")} />
          {lg.market_open ? "Mercado abierto · cierra en" : "Mercado cerrado · abre en"}
        </div>
        <div className="mkt__time num">{lg.market_open ? closes : (opens ?? "—")}</div>
        <div className="mkt__sub">
          {lg.market_open
            ? `${market?.listings?.length ?? 0} jugadores a subasta · gana la puja más alta`
            : `Próxima apertura ${fmtWhen(lg.market_opens_at)} · ${lg.market_size} jugadores`}
        </div>
        {lg.market_open && <div className="progress"><div className="progress__fill" style={{ width: `${100 - pct}%` }} /></div>}
        {admin && (
          <div style={{ marginTop: 12 }}>
            {lg.market_open
              ? <button className="btn btn--sm btn--quiet" disabled={busy} onClick={onForceClose}>
                  <IconClose size={14} />Cerrar ya y resolver pujas
                </button>
              : <button className="btn btn--sm btn--quiet" disabled={busy} onClick={onForceOpen}>
                  <IconPlay size={13} />Abrir mercado ya
                </button>}
          </div>
        )}
      </div>

      {committed > 0 && (
        <div className="budget">
          <div>
            <div className="muted" style={{ fontSize: "var(--fs-2xs)", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              Libre
            </div>
            <div className="budget__n">{free} M€</div>
          </div>
          <div className="budget__bar">
            <div className="budget__used"
              style={{ width: `${Math.min(100, (committed / Math.max(1, market.my_budget)) * 100)}%` }} />
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="muted" style={{ fontSize: "var(--fs-2xs)", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              En pujas
            </div>
            <div className="budget__n" style={{ color: "var(--clause)" }}>{r1(committed)} M€</div>
          </div>
        </div>
      )}

      {!lg.market_open
        ? <Empty icon={<IconMarket size={22} />} title="El mercado está cerrado">
            Vuelve cuando abra para pujar por los jugadores de la tanda.
          </Empty>
        : !market ? <SkeletonList n={5} />
          : market.listings.length === 0
            ? <Empty icon={<IconMarket size={22} />} title="No hay jugadores en esta tanda" />
            : market.listings.map((l: any) => (
              <PlayerRow key={l.listing_id} p={l} onOpen={() => onOpenPlayer(l.player_id)}
                tone={l.my_bid ? "bid" : undefined}
                right={<>
                  {l.my_bid != null && <span className="chip chip--pos">Tu puja <b>{l.my_bid}</b></span>}
                  <button className="btn btn--sm" disabled={busy}
                    onClick={(e) => { e.stopPropagation(); onBid(l); }}>
                    {l.my_bid != null ? "Cambiar" : "Pujar"}
                  </button>
                </>} />
            ))}
    </>
  );
}

/* ------------------------------------------------------------ clasificación */
function TableTab({ data, lg, jr, onJornada, onManager }: any) {
  const [view, setView] = useState<"jornada" | "general">(
    (jr?.rows ?? []).length > 0 ? "jornada" : "general");
  const js: number[] = jr?.jornadas ?? [];
  const i = js.indexOf(jr?.jornada);
  const rows: any[] = jr?.rows ?? [];

  return (
    <>
      <div style={{ margin: "4px 0 12px" }}>
        <Segmented value={view} onChange={setView} options={[
          { v: "jornada", label: "Jornada" },
          { v: "general", label: "General" },
        ]} />
      </div>

      {view === "jornada" && (rows.length === 0 ? (
        <Empty icon={<IconTrophy size={22} />} title="Aún no hay ninguna jornada puntuada">
          Cuando se puntúe la primera jornada verás aquí quién más sumó.
        </Empty>
      ) : (
        <>
          <div className="jnav">
            <button className="iconbtn iconbtn--framed" disabled={i <= 0} aria-label="Jornada anterior"
              onClick={() => onJornada(js[i - 1])}><IconChevronLeft size={18} /></button>
            <div className="jnav__title">
              <span>Clasificación de la</span>
              <b>Jornada {jr.jornada}</b>
            </div>
            <button className="iconbtn iconbtn--framed" disabled={i < 0 || i >= js.length - 1}
              aria-label="Jornada siguiente" onClick={() => onJornada(js[i + 1])}>
              <IconChevronRight size={18} />
            </button>
          </div>

          <div className="podium">
            {rows.slice(0, 3).map((r: any) => (
              <div key={r.member_id}
                className={`pod pod--${r.pos}` + (r.member_id === data.my_member_id ? " is-me" : "")}>
                <span className="pod__pos num">{r.pos}</span>
                <span className="pod__name">{r.manager}</span>
                <span className="pod__pts num">{r.points}<span>pts</span></span>
              </div>
            ))}
          </div>

          {rows.length > 3 && (
            <div className="list">
              {rows.slice(3).map((r: any) => (
                <div key={r.member_id}
                  className={"lrow" + (r.member_id === data.my_member_id ? " is-me" : "")}>
                  <span className="lrow__pos">{r.pos}</span>
                  <span className="lrow__who"><b>{r.manager}</b></span>
                  <span className="lrow__pts">{r.points}</span>
                </div>
              ))}
            </div>
          )}
          <p className="hint" style={{ marginTop: 12 }}>
            Puntos de esa jornada: la suma de los <b>puntos fantasy</b> de los cinco titulares.
          </p>
        </>
      ))}

      {view === "general" && (
        <>
          <div className="list">
            {data.standings.map((r: any) => (
              <button key={r.member_id}
                className={"lrow lrow--tap" + (r.member_id === data.my_member_id ? " is-me" : "")}
                onClick={() => onManager(r.member_id)}>
                <span className="lrow__pos">{r.rank}</span>
                <span className="lrow__who">
                  <b>{r.manager}</b>
                  <small>{r.squad_count}/{lg.squad_size} jugadores · {r.squad_value} M€ en plantilla</small>
                </span>
                <span className="lrow__pts">{r.total_points}</span>
              </button>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 12 }}>
            Toca un mánager para ver su plantilla y pagar cláusulas.
          </p>
        </>
      )}
    </>
  );
}
