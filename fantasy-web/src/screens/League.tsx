/* ============================================================================
   Pantalla de una liga: equipo, mercado (subastas + cláusulas), clasificación
   por jornada y actividad.
   ========================================================================== */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Me } from "../App";
import {
  IconActivity, IconAlert, IconArrowLeft, IconCheck, IconCopy, IconMarket,
  IconPlay, IconSquad, IconStar, IconStarOn, IconTrophy,
} from "../icons";
import { ClauseMeta, Delta, FeedRow, PlayerRow, fp } from "../parts";
import {
  Empty, HalfCourt, Loading, Photo, Section, prettyName, useCountdown,
} from "../ui";
import MarketTab from "./Market";
import TableTab from "./Table";
import { BidSheet, ClauseSheet, ManagerJornadaSheet, ManagerSheet, PlayerSheet } from "./sheets";

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
  const [marketView, setMarketView] = useState<"subastas" | "clausulas">("subastas");
  const [data, setData] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [clauses, setClauses] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [bidFor, setBidFor] = useState<any>(null);
  const [playerFor, setPlayerFor] = useState<number | null>(null);
  const [rivalFor, setRivalFor] = useState<any>(null);
  const [jornadaFor, setJornadaFor] = useState<any>(null);
  const [clauseFor, setClauseFor] = useState<any>(null);
  const [jr, setJr] = useState<any>(null);
  const inited = useRef(false);

  async function load() { const d = await api.league(id); setData(d); return d; }
  async function loadMarket() { const m = await api.market(id); setMarket(m); return m; }
  async function loadClauses() { const c = await api.clauses(id); setClauses(c); return c; }

  useEffect(() => {
    load().then((d) => {
      if (inited.current) return;
      inited.current = true;
      if (d.league.market_open) { setTab("mercado"); loadMarket(); }
    });
  }, [id]);
  // al cambiar de pestaña refrescamos: la liga es en vivo (fichajes, cláusulas, mánagers)
  useEffect(() => {
    load();
    if (tab === "mercado") { loadMarket(); loadClauses().catch(() => setClauses({ players: [] })); }
  }, [tab]);
  useEffect(() => {
    if (tab !== "mercado" || !data?.league?.market_open) return;
    const t = setInterval(() => { loadMarket(); load(); }, 20000);
    return () => clearInterval(t);
  }, [tab, data?.league?.market_open]);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 2800); return () => clearTimeout(t); }, [msg]);
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
      if (clauses) await loadClauses();
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

  function openManager(r: any) {
    // desde la jornada ya tenemos su desglose; desde la general hay que pedir la plantilla
    if (r.players) setJornadaFor({ ...r, jornada: jr?.jornada });
    else api.memberSquad(id, r.member_id).then(setRivalFor).catch(() => {});
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
            <button className="meta" onClick={() => {
              navigator.clipboard?.writeText(lg.join_code);
              setMsg({ text: "Código copiado" });
            }}>
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
          <MarketTab lg={lg} market={market} clauses={clauses} admin={admin} busy={busy}
            closes={closes} opens={opens} view={marketView} onView={setMarketView}
            onOpenPlayer={setPlayerFor} onBid={setBidFor} onClause={setClauseFor}
            onForceOpen={() => act(() => api.openMarket(id), "Mercado abierto")}
            onForceClose={() => act(() => api.closeMarket(id), "Mercado cerrado y pujas resueltas")} />
        )}

        {tab === "liga" && (
          <TableTab data={data} lg={lg} jr={jr}
            onJornada={(j: number) => api.jornada(id, j).then(setJr).catch(() => {})}
            onManager={openManager} />
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
          onClause={(p: any) => { setPlayerFor(null); setClauseFor(p); }}
          onRaise={async (pid: number, v: number) => { setPlayerFor(null); await act(() => api.raiseClause(id, pid, v), "Cláusula subida"); }}
          onSell={async (pid: number) => { setPlayerFor(null); await act(() => api.sell(id, pid), "Jugador vendido"); }} />
      )}

      {clauseFor && (
        <ClauseSheet p={clauseFor} free={freeBudget} lockH={lg.clause_lock_h} busy={busy}
          onClose={() => setClauseFor(null)}
          onConfirm={async () => {
            const who = prettyName(clauseFor.name);
            setClauseFor(null);
            await act(() => api.payClause(id, clauseFor.player_id), `¡Clausulazo! ${who} es tuyo`);
          }} />
      )}

      {rivalFor && (
        <ManagerSheet data={rivalFor} free={freeBudget} onClose={() => setRivalFor(null)}
          onPlayer={(pid) => { setRivalFor(null); setPlayerFor(pid); }}
          onClause={(p: any) => { setRivalFor(null); setClauseFor(p); }} />
      )}

      {jornadaFor && (
        <ManagerJornadaSheet row={jornadaFor} onClose={() => setJornadaFor(null)} />
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
        : p.starter ? "Quitar del quinteto" : "Poner en el quinteto"}
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
              {p && <span className="tok__sub num">{p.departed ? "0" : fp(p).toFixed(1)} PF</span>}
            </div>
          );
        })}
      </div>

      <div className="lineup">
        <div style={{ flex: 1 }}>
          <div className="lineup__k">Proyección por jornada</div>
          <div className="lineup__note">Lo que suma tu quinteto con su media de puntos fantasy</div>
        </div>
        <div className="lineup__v num">{lineupFp}</div>
      </div>

      {gone.length > 0 && (
        <div className="notice">
          <span className="notice__ico"><IconAlert size={18} /></span>
          <div>
            <b>{gone.length === 1
              ? "Un jugador tuyo ha fichado por otro equipo"
              : `${gone.length} jugadores tuyos han fichado por otro equipo`}</b>
            <span>{goneStarters.length === 1
              ? "Tienes a uno en el quinteto y sumará 0 puntos: cámbialo o véndelo desde su ficha."
              : goneStarters.length > 1
                ? `Tienes a ${goneStarters.length} en el quinteto y sumarán 0 puntos: cámbialos o véndelos desde su ficha.`
                : "Ocupan sitio en la plantilla pero ya no puntúan. Véndelos para hacer hueco."}</span>
          </div>
        </div>
      )}

      <Section right={`${starters.length}/${lg.lineup_size}`}>Quinteto titular</Section>
      {starters.length === 0 && (
        <Empty icon={<IconSquad size={22} />} title="No has alineado a nadie">
          Marca con la estrella a {lg.lineup_size} jugadores de tu plantilla.
        </Empty>
      )}
      {starters.map((p: any) => (
        <PlayerRow key={p.player_id} p={p} onOpen={() => onOpen(p.player_id)}
          tone={p.departed ? "gone" : "starter"}
          meta={<><Delta v={p.delta} /><ClauseMeta p={p} /></>}
          right={<StarBtn p={p} />} />
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
          meta={<><Delta v={p.delta} /><ClauseMeta p={p} /></>}
          right={<StarBtn p={p} />} />
      ))}
    </>
  );
}
