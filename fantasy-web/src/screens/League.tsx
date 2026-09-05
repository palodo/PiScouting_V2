/* ============================================================================
   Pantalla de una liga: equipo, mercado (subastas + cláusulas), jugadores,
   clasificación por jornada y apuestas.
   ========================================================================== */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Me } from "../App";
import {
  IconAlert, IconArrowLeft, IconCheck, IconCoin, IconCopy, IconLock,
  IconMarket, IconPlay, IconSearch, IconSquad, IconStar, IconStarOn, IconTrophy,
} from "../icons";
import { ClauseMeta, Delta, PlayerRow, fp, phaseInfo } from "../parts";
import {
  Empty, HalfCourt, Loading, Photo, Section, prettyName, useCountdown,
} from "../ui";
import MarketTab from "./Market";
import BetsTab from "./Bets";
import OffersTab from "./Offers";
import PlayersTab from "./Players";
import NotificationBell from "./Notifications";
import TableTab from "./Table";
import {
  BidSheet, ClauseSheet, InviteSheet, ManagerJornadaSheet, ManagerSheet, MatchesSheet,
  OfferSheet, PlayerSheet, ScoringSheet,
} from "./sheets";

type Tab = "equipo" | "mercado" | "jugadores" | "liga" | "apuestas";
// La actividad se ha mudado a la campana, junto a los avisos propios: es algo que se lee
// de vez en cuando, y el sitio lo aprovechan mejor las apuestas, que hay que ir a hacerlas.
const TABS: [Tab, (p: any) => any, string][] = [
  ["equipo", IconSquad, "Equipo"],
  ["mercado", IconMarket, "Mercado"],
  ["jugadores", IconSearch, "Jugadores"],
  ["liga", IconTrophy, "Liga"],
  ["apuestas", IconCoin, "Apuestas"],
];

/** Posiciones de los cinco titulares sobre la media pista. */
const SLOTS = [
  { left: "50%", top: "80%" }, { left: "17%", top: "63%" }, { left: "83%", top: "63%" },
  { left: "30%", top: "35%" }, { left: "70%", top: "31%" },
];

const r1 = (n: number) => Math.round(n * 10) / 10;

export default function League({ id, me, onBack }: { id: number; me: Me; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("equipo");
  const [marketView, setMarketView] = useState<"subastas" | "clausulas" | "ofertas">("subastas");
  const [data, setData] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [clauses, setClauses] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [bidFor, setBidFor] = useState<any>(null);
  // {id, jornada?}: con jornada, la ficha abre por el partido de ese día
  const [playerFor, setPlayerFor] = useState<{ id: number; jornada?: number } | null>(null);
  const [rivalFor, setRivalFor] = useState<any>(null);
  const [jornadaFor, setJornadaFor] = useState<any>(null);
  const [clauseFor, setClauseFor] = useState<any>(null);
  const [scoring, setScoring] = useState(false);
  const [jr, setJr] = useState<any>(null);
  const [matchesFor, setMatchesFor] = useState<any>(null);
  const [invitando, setInvitando] = useState(false);
  const [offers, setOffers] = useState<any>(null);
  const [players, setPlayers] = useState<any>(null);
  const [offerFor, setOfferFor] = useState<any>(null);
  const [bets, setBets] = useState<any>(null);
  const inited = useRef(false);

  async function load() { const d = await api.league(id); setData(d); return d; }
  async function loadMarket() { const m = await api.market(id); setMarket(m); return m; }
  async function loadClauses() { const c = await api.clauses(id); setClauses(c); return c; }
  async function loadOffers() { const o = await api.offers(id); setOffers(o); return o; }
  async function loadPlayers() { const p = await api.players(id); setPlayers(p); return p; }
  async function loadBets() { const b = await api.bets(id); setBets(b); return b; }
  function openMatches(jornada?: number) {
    setMatchesFor({ loading: true });
    api.matches(id, jornada).then(setMatchesFor).catch(() => setMatchesFor(null));
  }

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
    loadOffers().catch(() => setOffers({ received: [], sent: [] }));
    if (tab === "mercado") { loadMarket(); loadClauses().catch(() => setClauses({ players: [] })); }
    if (tab === "jugadores" && !players) loadPlayers().catch(() => setPlayers({ players: [] }));
    if (tab === "apuestas") loadBets().catch(() => setBets({ options: [], my_bets: [] }));
  }, [tab]);
  useEffect(() => {
    if (tab !== "mercado" || !data?.league?.market_open) return;
    const t = setInterval(() => { loadMarket(); load(); }, 20000);
    return () => clearInterval(t);
  }, [tab, data?.league?.market_open]);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 2800); return () => clearTimeout(t); }, [msg]);
  useEffect(() => { setJr(data?.jornada_ranking ?? null); }, [data?.jornada_ranking]);

  // La fase (mercado / último cambio de quinteto / jornada en juego) manda en toda la pantalla.
  const ph = phaseInfo(data?.league);
  const phaseLeft = useCountdown(ph.until);

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
      await loadOffers().catch(() => {});
      if (players) await loadPlayers().catch(() => {});
      if (bets) await loadBets().catch(() => {});
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

  const openPlayer = (id: number, jornada?: number) => setPlayerFor({ id, jornada });

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
            <NotificationBell feed={data.feed} />
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
            <button className={"meta" + (ph.live ? " meta--live" : "")}
              onClick={() => openMatches(ph.j)}>
              <span className="meta__k">
                <span className={"livedot" + (ph.live ? "" : " livedot--off")} />
                {ph.chip}
              </span>
              <span className="meta__v num">{phaseLeft ?? "—"}</span>
            </button>
            <button className="meta" onClick={() => setScoring(true)}>
              <span className="meta__k">Jornada</span>
              <span className="meta__v num">{lg.current_jornada}<span className="muted">/{lg.max_jornada}</span></span>
            </button>
            {data.my_budget != null && (
              <div className="meta meta--money">
                <span className="meta__k">Saldo</span>
                <span className="meta__v num">{r1(data.my_budget)} M€</span>
              </div>
            )}
            <button className="meta" onClick={() => setInvitando(true)}>
              <span className="meta__k">Código</span>
              <span className="meta__v">{lg.join_code}<IconCopy size={13} /></span>
            </button>
          </div>
        </div>
      </header>

      <main className="wrap wrap--tabbed">
        {tab === "equipo" && (
          <TeamTab lg={lg} squad={squad} starters={starters} bench={bench} busy={busy}
            ph={ph} left={phaseLeft} onOpen={openPlayer} onToggle={toggleStarter}
            onMatches={openMatches}
            onScoring={() => setScoring(true)} />
        )}

        {tab === "mercado" && (
          <MarketTab lg={lg} market={market} clauses={clauses} admin={admin} busy={busy}
            offers={offers}
            offersUI={<OffersTab data={offers} busy={busy}
              onOpen={(pid: number) => openPlayer(pid)}
              onAccept={(o: any) => act(() => api.resolveOffer(id, o.id, true),
                o.from ? `Traspaso cerrado: ${o.amount} M€` : `Vendido por ${o.amount} M€`)}
              onReject={(o: any) => act(() => api.resolveOffer(id, o.id, false), "Oferta rechazada")} />}
            view={marketView} onView={setMarketView}
            onOpenPlayer={openPlayer} onBid={setBidFor} onClause={setClauseFor}
            onForceOpen={() => act(() => api.openMarket(id), "Mercado abierto")}
            onForceClose={() => act(() => api.closeMarket(id), "Mercado cerrado y pujas resueltas")} />
        )}

        {tab === "jugadores" && (
          <PlayersTab data={players} onOpen={(pid: number) => openPlayer(pid)} />
        )}

        {tab === "liga" && (
          <TableTab data={data} lg={lg} jr={jr}
            onJornada={(j: number) => api.jornada(id, j).then(setJr).catch(() => {})}
            onManager={openManager} onPlayer={openPlayer} />
        )}

        {tab === "apuestas" && (
          <BetsTab data={bets} busy={busy}
            onBet={(ids: number[], stake: number) =>
              act(() => api.placeBet(id, ids, stake), `Apuesta de ${stake} M€ hecha`)} />
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
        <PlayerSheet leagueId={id} playerId={playerFor.id} jornada={playerFor.jornada}
          league={lg} busy={busy}
          myMemberId={data.my_member_id} freeBudget={freeBudget}
          onClose={() => setPlayerFor(null)}
          onClause={(p: any) => { setPlayerFor(null); setClauseFor(p); }}
          onRaise={async (pid: number, v: number) => { setPlayerFor(null); await act(() => api.raiseClause(id, pid, v), "Cláusula subida"); }}
          onSell={async (pid: number) => {
            setPlayerFor(null);
            await act(() => api.sell(id, pid), "En venta: te llegará una oferta al día");
          }}
          onCancelSale={async (pid: number) => {
            setPlayerFor(null);
            await act(() => api.cancelSale(id, pid), "Retirado de la venta");
          }}
          onOffer={(p: any) => { setPlayerFor(null); setOfferFor(p); }} />
      )}

      {offerFor && (
        <OfferSheet p={offerFor} free={freeBudget} busy={busy}
          onClose={() => setOfferFor(null)}
          onSend={async (amount: number) => {
            const quien = offerFor.owner ?? "su mánager";
            setOfferFor(null);
            await act(() => api.makeOffer(id, offerFor.player_id, amount),
              `Oferta enviada a ${quien}`);
          }} />
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
        <ManagerSheet data={rivalFor} free={freeBudget} canTrade={lg.can_trade ?? true}
          onClose={() => setRivalFor(null)}
          onPlayer={(pid) => { setRivalFor(null); openPlayer(pid); }}
          onClause={(p: any) => { setRivalFor(null); setClauseFor(p); }} />
      )}

      {invitando && (
        <InviteSheet lg={lg} onClose={() => setInvitando(false)}
          onCopied={(text) => setMsg({ text })} />
      )}

      {matchesFor && (
        <MatchesSheet data={matchesFor.loading ? null : matchesFor}
          onClose={() => setMatchesFor(null)} />
      )}

      {jornadaFor && (
        <ManagerJornadaSheet row={jornadaFor} onClose={() => setJornadaFor(null)}
          onPlayer={(pid, j) => { setJornadaFor(null); openPlayer(pid, j); }} />
      )}

      {scoring && <ScoringSheet lg={lg} onClose={() => setScoring(false)} />}

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
              {k === "mercado" && tab !== "mercado"
                && ((offers?.received?.length ?? 0) > 0 || lg.market_open)
                && <span className="tab__badge" />}
              {k === "apuestas" && tab !== "apuestas"
                && (bets?.my_bets ?? []).some((b: any) => b.status === "pending")
                && <span className="tab__badge" />}
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}

/* ------------------------------------------------------------------ equipo */
function TeamTab({ lg, squad, starters, bench, busy, ph, left, onOpen, onToggle, onScoring,
  onMatches }: any) {
  const gone = squad.filter((p: any) => p.departed);
  const goneStarters = gone.filter((p: any) => p.starter);
  const lineupFp = r1(starters.reduce((a: number, p: any) => a + (p.departed ? 0 : fp(p)), 0));
  const canLineup = (lg.can_lineup ?? true) as boolean;

  const StarBtn = ({ p }: { p: any }) => (
    <button className={"iconbtn" + (p.starter ? " is-on" : "")}
      disabled={busy || p.departed || !canLineup}
      title={!canLineup ? "El quinteto está cerrado"
        : p.departed ? "Ya no puntúa en esta conferencia"
          : p.starter ? "Quitar del quinteto" : "Poner en el quinteto"}
      onClick={(e) => { e.stopPropagation(); onToggle(p.player_id, p.starter); }}>
      {p.starter ? <IconStarOn size={19} /> : <IconStar size={19} />}
    </button>
  );

  return (
    <>
      {ph.phase === "alineacion" && (
        <div className="notice notice--info">
          <span className="notice__ico"><IconAlert size={18} /></span>
          <div>
            <b>Última llamada para el quinteto</b>
            <span>La jornada {ph.j} empieza en {left ?? "nada"}. Después no se
              podrá tocar nada hasta que termine.</span>
            <button className="linkbtn" onClick={() => onMatches(ph.j)}>Ver los partidos</button>
          </div>
        </div>
      )}
      {ph.phase === "jornada" && (
        <div className="notice notice--info">
          <span className="notice__ico"><IconLock size={18} /></span>
          <div>
            <b>Jornada {ph.j} en juego</b>
            <span>{ph.note} {left ? `Quedan ${left}.` : ""}</span>
            <button className="linkbtn" onClick={() => onMatches(ph.j)}>Ver qué falta por jugarse</button>
          </div>
        </div>
      )}

      <div className="court">
        <HalfCourt />
        {SLOTS.map((pos, i) => {
          const p = starters[i];
          // los cinco de la pista también abren ficha: es donde primero se toca
          return (
            <div key={i} style={pos as any} onClick={p ? () => onOpen(p.player_id) : undefined}
              className={"tok" + (p ? " tok--tap" : " tok--empty") + (p?.departed ? " tok--gone" : "")}>
              <Photo code={p?.feb_code} name={p?.name} variant="tok" />
              <span className="tok__tag">{p ? prettyName(p.name).split(" ").slice(-1)[0] : "Libre"}</span>
              {p && <span className="tok__sub num">{fp(p).toFixed(1)} PF</span>}
            </div>
          );
        })}
      </div>

      <button className="lineup" onClick={onScoring}>
        <div style={{ flex: 1, textAlign: "left" }}>
          <div className="lineup__k">Proyección por jornada</div>
          <div className="lineup__note">
            Lo que suma tu quinteto con su media de puntos fantasy · cómo se calculan
          </div>
        </div>
        <div className="lineup__v num">{lineupFp}</div>
      </button>

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
