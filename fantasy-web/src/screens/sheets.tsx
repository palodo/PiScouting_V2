/* ============================================================================
   Hojas inferiores: ficha del jugador, puja y plantilla de un rival.
   ========================================================================== */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import {
  IconBolt, IconCalendar, IconCheck, IconClock, IconClose, IconCoin, IconCopy, IconGavel,
  IconLock, IconMinus, IconPlus, IconShare, IconSquad, IconWhatsApp,
} from "../icons";
import { PfBox, PlayerRow, fp, lockLabel } from "../parts";
import {
  HalfCourt, Loading, Photo, Section, Sheet, SheetClose, fmtWhen, fullName, prettyName,
  prettyTeam,
} from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

/* ---------------------------------------------------------- ficha completa */
export function PlayerSheet({ leagueId, playerId, jornada, league, myMemberId, freeBudget, busy,
  onClose, onClause, onRaise, onSell, onCancelSale, onOffer }: any) {
  const [d, setD] = useState<any>(null);
  const [mode, setMode] = useState<"view" | "raise" | "sell">("view");
  const [newClause, setNewClause] = useState(0);

  useEffect(() => {
    setD(null); setMode("view");
    api.player(leagueId, playerId, jornada).then((x) => {
      setD(x);
      setNewClause(r1((x.clause ?? 0) + 10));
    }).catch(() => setD(false));
  }, [leagueId, playerId, jornada]);

  if (d === false) {
    return <Sheet onClose={onClose}><div className="empty"><b>No se pudo cargar la ficha</b></div></Sheet>;
  }
  if (!d) return <Sheet onClose={onClose}><Loading label="Cargando ficha" /></Sheet>;

  const wb = d.win_bonus ?? league?.win_bonus ?? 0;
  const games: any[] = d.last ?? [];
  // los puntos de cada partido los manda el backend (val + bonus + su +/- en pista);
  // el cálculo local es solo por si respondiera una versión antigua
  const gamePts = (g: any) => g.fp ?? r1(g.val + (g.won ? wb : 0));
  // La media la manda el backend (misma ventana de jornadas que las listas); el total
  // sale de los datos de la ficha para que cuadre con los PJ y el V-D de arriba.
  const fpAvg = d.fp_avg ?? (d.games ? r1(d.avg.val + (wb * d.wins) / d.games) : 0);
  const fpForm = d.fp_form ?? (games.length
    ? r1(games.slice(-3).reduce((a, g) => a + gamePts(g), 0) / Math.min(3, games.length)) : 0);
  const fpTotal = Math.round(d.avg.val * (d.games ?? 0) + wb * (d.wins ?? 0));
  const maxPts = Math.max(...games.map((g) => Math.abs(gamePts(g))), 1);

  const mine = d.owner_member_id && d.owner_member_id === myMemberId;
  const rival = d.owner_member_id && d.owner_member_id !== myMemberId;
  const raiseCost = r1((newClause - (d.clause ?? 0)) * (league?.clause_raise_cost ?? 0.25));
  // Fuera de la fase de mercado no se mueve dinero: ni clausulazos, ni ventas, ni blindajes.
  const canTrade = (league?.can_trade ?? true) as boolean;

  return (
    <Sheet onClose={onClose} title={fullName(d.name)}>
      <div className="sheet__head">
        <Photo code={d.feb_code} name={d.name} variant="lg" />
        <div className="sheet__body">
          <h2>{fullName(d.name)}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>{prettyTeam(d.team)}</div>
          <div className="chiprow" style={{ marginTop: 7 }}>
            <span className="chip chip--accent"><b>{d.price}</b> M€</span>
            <span className="chip">{d.games} PJ</span>
            <span className="chip">{d.wins}V · {d.losses}D</span>
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      {/* Si se abre desde una jornada, lo primero es ese partido: es lo que se venía a ver */}
      {d.game && <GameLine g={d.game} />}

      {/* Contra quién juega: lo que decides mirar antes de alinearlo */}
      {!d.game && d.next_match && <NextMatch n={d.next_match} />}

      {/* Lo que de verdad suma en la liga */}
      <div className="fp">
        <div>
          <span className="fp__k">Puntos fantasy · media</span>
          <span className="fp__v num">{fpAvg}</span>
          <span className="fp__note">VAL {d.avg.val} + {wb} por victoria + su +/- en pista</span>
        </div>
        <div className="fp__side">
          <div><b className="num">{fpTotal}</b><span>temporada</span></div>
          <div><b className="num">{fpForm}</b><span>forma</span></div>
        </div>
      </div>

      <Section>Últimas jornadas</Section>
      {games.length === 0
        ? <p className="hint">Todavía no ha jugado esta temporada.</p>
        : (
          <div className="spark">
            {games.map((g, i) => {
              const v = gamePts(g);
              return (
                <div key={i} className="spark__col" title={`Jornada ${g.j}: ${v} PF`}>
                  <span className="spark__v">{v}</span>
                  <span className={"spark__bar" + (g.won ? " spark__bar--win" : v < 0 ? " spark__bar--neg" : "")}
                    style={{ height: `${Math.max(3, (Math.abs(v) / maxPts) * 52)}px` }} />
                  <span className="spark__j">J{g.j}</span>
                </div>
              );
            })}
          </div>
        )}

      <Section>Promedios de la temporada</Section>
      <div className="stats stats--hero">
        {[["PTS", d.avg.pts], ["REB", d.avg.reb], ["AST", d.avg.ast], ["VAL", d.avg.val]].map(([k, v]) => (
          <div key={k as string} className="stat"><b>{v as number}</b><span>{k as string}</span></div>
        ))}
      </div>
      <div className="stats stats--6">
        {[["MIN", d.avg.min], ["ROB", d.avg.stl], ["TAP", d.avg.blk], ["PER", d.avg.tov],
          ["+/-", d.avg.pm], ["FLT", d.avg.pf]].map(([k, v]) => (
          <div key={k as string} className="stat"><b>{v as number}</b><span>{k as string}</span></div>
        ))}
      </div>
      <div className="stats stats--5">
        {[["T. campo", d.pct.fg], ["2P", d.pct.t2], ["3P", d.pct.t3], ["TL", d.pct.tl], ["TS", d.pct.ts]]
          .map(([k, v]) => (
            <div key={k as string} className="stat"><b>{v as number}%</b><span>{k as string}</span></div>
          ))}
      </div>

      <Section>Situación</Section>
      {!d.owner && <p className="hint">Jugador libre: puede salir a subasta en el mercado.</p>}
      {d.owner && (
        <div className="clausebox">
          <span style={{ color: "var(--clause)" }}><IconBolt size={22} strokeWidth={2} /></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span className="clausebox__k">{mine ? "Tu jugador" : `Plantilla de ${d.owner}`}</span>
            <div className="clausebox__v">{d.clause}<span> M€ de cláusula</span></div>
            {d.clause_locked && (
              <div className="muted" style={{ fontSize: "var(--fs-sm)", display: "flex", alignItems: "center", gap: 4 }}>
                <IconLock size={12} strokeWidth={2.2} />Blindado {lockLabel(d.clause_lock_mins)}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="sheet__actions">
        {!canTrade && (mine || rival) && (
          <p className="hint" style={{ margin: 0 }}>
            El mercado está cerrado por la jornada: ni cláusulas ni ventas hasta que vuelva a abrir.
          </p>
        )}

        {rival && (
          <button className="btn btn--clause btn--block"
            disabled={busy || !canTrade || d.clause_locked || d.clause > freeBudget}
            onClick={() => onClause(d)}>
            <IconBolt size={17} strokeWidth={2.2} />
            {!canTrade ? "Mercado cerrado"
              : d.clause_locked ? "Blindado ahora mismo"
                : d.clause > freeBudget ? `Te faltan ${r1(d.clause - freeBudget)} M€`
                  : `Pagar cláusula · ${d.clause} M€`}
          </button>
        )}

        {rival && (
          <button className="btn btn--ghost btn--block" disabled={busy || !canTrade}
            onClick={() => onOffer({ ...d, owner: d.owner })}>
            <IconCoin size={17} />Hacerle una oferta a {d.owner}
          </button>
        )}

        {mine && mode === "view" && (
          <>
            <button className="btn btn--ghost btn--block" disabled={!canTrade}
              onClick={() => setMode("raise")}>
              <IconLock size={17} />Subir cláusula
            </button>
            <button className={"btn btn--block " + (d.on_sale ? "btn--quiet" : "btn--danger")}
              disabled={!canTrade}
              onClick={() => d.on_sale ? onCancelSale(d.player_id) : setMode("sell")}>
              {d.on_sale ? "Retirar de la venta" : "Poner en venta"}
            </button>
          </>
        )}

        {mine && mode === "sell" && (
          <>
            <p className="hint" style={{ margin: 0 }}>
              No se vende al instante. Durante <b>3 días</b> la liga te mandará{" "}
              <b>una oferta al día</b>, entre un 5 % menos y un 10 % más de su valor
              ({d.price} M€). <b>Cada una solo vale 24 horas</b>: cuando llegue la
              siguiente, la anterior se pierde, así que no puedes esperar a verlas todas
              y quedarte la mejor. Mientras tanto sigue siendo tuyo y puede jugar.
            </p>
            <button className="btn btn--danger btn--block" disabled={busy}
              onClick={() => onSell(d.player_id)}>
              <IconCheck size={17} />Ponerlo en venta
            </button>
            <button className="btn btn--quiet btn--block" onClick={() => setMode("view")}>Cancelar</button>
          </>
        )}

        {mine && mode === "raise" && (
          <>
            <div className="stepper">
              <button className="stepper__btn" aria-label="Bajar"
                onClick={() => setNewClause((v) => Math.max(d.clause + 0.5, r1(v - 5)))}>
                <IconMinus size={20} />
              </button>
              <input type="number" step="0.5" value={newClause} inputMode="decimal"
                onChange={(e) => setNewClause(Number(e.target.value))} />
              <button className="stepper__btn" aria-label="Subir"
                onClick={() => setNewClause((v) => r1(v + 5))}>
                <IconPlus size={20} />
              </button>
            </div>
            <p className="hint" style={{ margin: 0 }}>
              Subirla de {d.clause} a {newClause} M€ cuesta <b>{raiseCost} M€</b>.
              Tienes {r1(freeBudget)} M€ libres.
            </p>
            <button className="btn btn--block" disabled={busy || newClause <= d.clause || raiseCost > freeBudget}
              onClick={() => onRaise(d.player_id, newClause)}>Confirmar subida</button>
            <button className="btn btn--quiet btn--block" onClick={() => setMode("view")}>Cancelar</button>
          </>
        )}
      </div>
    </Sheet>
  );
}

/** El partido de una jornada concreta: el acta entera y de dónde salen sus puntos. */
function GameLine({ g }: { g: any }) {
  // Mismas rejillas que los promedios de más abajo, para que la ficha se lea de un tirón.
  const Row = ({ mod, cells }: { mod?: string; cells: [string, any][] }) => (
    <div className={"stats" + (mod ? ` stats--${mod}` : "")}>
      {cells.map(([k, v]) => (
        <div key={k} className="stat"><b>{v}</b><span>{k}</span></div>
      ))}
    </div>
  );
  return (
    <div className="game">
      <div className="game__top">
        <div style={{ minWidth: 0 }}>
          <span className="game__k">Jornada {g.jornada}</span>
          <div className="game__vs">
            {g.home ? "vs " : "en "}{prettyTeam(g.rival) || "—"}
          </div>
          {g.score && (
            <span className={"game__res " + (g.won ? "is-win" : "is-loss")}>
              {g.won ? "Ganó" : "Perdió"} {g.score}
            </span>
          )}
        </div>
        <PfBox value={g.points} />
      </div>

      <Row mod="hero" cells={[["PTS", g.pts], ["REB", g.reb], ["AST", g.ast], ["VAL", g.val]]} />
      <Row mod="5" cells={[["MIN", g.min], ["T2", g.t2], ["T3", g.t3], ["TL", g.tl],
        ["+/-", g.pm > 0 ? `+${g.pm}` : g.pm]]} />
      <Row cells={[["ROB", g.stl], ["TAP", g.blk], ["PER", g.tov], ["FLT", g.pf]]} />

      <p className="game__note">
        {g.starter ? "Salió de titular. " : ""}
        <b>{g.points} PF</b> = {g.val} de valoración{g.win_bonus ? ` + ${g.win_bonus} por ganar` : ""}
        {g.pm_bonus ? `${g.pm_bonus > 0 ? " + " : " − "}${Math.abs(g.pm_bonus)} por su +/- en pista` : ""}.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ pujar */
export function BidSheet({ listing, budget, busy, onClose, onBid, onCancel }: {
  listing: any; budget: number; busy?: boolean; onClose: () => void;
  onBid: (amount: number) => void; onCancel?: () => void;
}) {
  const min = listing.price;
  const max = Math.max(min, r1(budget));
  const [amount, setAmount] = useState<number>(listing.my_bid ?? min);
  const step = (d: number) => setAmount((a) => Math.min(max, Math.max(min, r1(a + d))));
  const valid = amount >= min && amount <= max + 1e-6;

  return (
    <Sheet onClose={onClose} title="Pujar">
      <div className="sheet__head">
        <Photo code={listing.feb_code} name={listing.name} />
        <div className="sheet__body">
          <h2 style={{ fontSize: "var(--fs-lg)" }}>{fullName(listing.name)}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>{prettyTeam(listing.team)}</div>
          <div className="chiprow" style={{ marginTop: 6 }}>
            <span className="chip chip--accent">Salida <b>{min}</b> M€</span>
            <span className="chip"><IconGavel size={11} strokeWidth={2.2} />{listing.bids} puja{listing.bids === 1 ? "" : "s"}</span>
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      <div className="stepper">
        <button className="stepper__btn" aria-label="Bajar" onClick={() => step(-0.5)}><IconMinus size={20} /></button>
        <input type="number" step="0.1" value={amount} inputMode="decimal"
          onChange={(e) => setAmount(Number(e.target.value))} />
        <button className="stepper__btn" aria-label="Subir" onClick={() => step(0.5)}><IconPlus size={20} /></button>
      </div>
      <div className="quick">
        {[0, 1, 3, 5].map((d) => (
          <button key={d} onClick={() => setAmount(Math.min(max, r1(min + d)))}>
            {d === 0 ? "Salida" : `+${d}`}
          </button>
        ))}
      </div>
      <p className="hint" style={{ margin: "12px 0 0" }}>
        Puedes pujar hasta <b>{max} M€</b>. Las pujas son secretas: al cerrar el mercado
        se lleva al jugador la más alta.
      </p>

      <div className="sheet__actions">
        <button className="btn btn--block" disabled={!valid || busy} onClick={() => onBid(amount)}>
          {listing.my_bid ? "Actualizar puja" : "Pujar"} · {amount} M€
        </button>
        {onCancel && (
          <button className="btn btn--danger btn--block" disabled={busy} onClick={onCancel}>
            <IconClose size={16} />Retirar puja
          </button>
        )}
      </div>
    </Sheet>
  );
}

/* -------------------------------------------------------- plantilla rival */
export function ManagerSheet({ data, free, canTrade = true, onClose, onPlayer, onClause }: {
  data: any; free: number; canTrade?: boolean; onClose: () => void;
  onPlayer: (id: number) => void; onClause: (p: any) => void;
}) {
  return (
    <Sheet onClose={onClose} title={data.manager}>
      <div className="sheet__head" style={{ marginBottom: 4 }}>
        <div className="sheet__body">
          <h2>{data.manager}</h2>
          <div className="chiprow" style={{ marginTop: 6 }}>
            <span className="chip chip--accent"><b>{data.points}</b> pts</span>
            <span className="chip">{data.squad.length} jugadores</span>
            <span className="chip">{data.budget} M€ libres</span>
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>
      <p className="hint" style={{ margin: "12px 2px" }}>
        {canTrade
          ? <>Paga la cláusula y te lo llevas al momento. Tienes <b>{r1(free)} M€</b> libres.</>
          : <>El mercado está cerrado por la jornada: las cláusulas vuelven cuando acabe.</>}
      </p>
      <div>
        {data.squad.map((p: any) => (
          <PlayerRow key={p.player_id} p={p} onOpen={() => onPlayer(p.player_id)}
            tone={p.starter ? "starter" : undefined}
            right={p.clause_locked
              ? <span className="lockchip"><IconLock size={11} strokeWidth={2.4} />{lockLabel(p.clause_lock_mins)}</span>
              : <button className={"btn btn--sm " + (p.clause <= free && canTrade ? "btn--clause" : "btn--quiet")}
                  disabled={p.clause > free || !canTrade}
                  onClick={(e) => { e.stopPropagation(); onClause({ ...p, owner: data.manager }); }}>
                  <IconBolt size={13} strokeWidth={2.2} />{p.clause}
                </button>} />
        ))}
      </div>
    </Sheet>
  );
}

/* ------------------------------------------- confirmación del clausulazo */
export function ClauseSheet({ p, free, lockH, busy, onClose, onConfirm }: {
  p: any; free: number; lockH: number; busy?: boolean;
  onClose: () => void; onConfirm: () => void;
}) {
  const left = r1(free - (p.clause ?? 0));
  return (
    <Sheet onClose={onClose} title="Clausulazo">
      <div className="clausehero">
        <span className="clausehero__ico"><IconBolt size={26} strokeWidth={2} /></span>
        <span className="clausehero__k">Clausulazo</span>
        <span className="clausehero__v num">{p.clause}<span> M€</span></span>
      </div>

      <div className="prow" style={{ marginTop: 12 }}>
        <Photo code={p.feb_code} name={p.name} />
        <div className="prow__body">
          <div className="prow__name">{prettyName(p.name)}</div>
          <div className="prow__team">{prettyTeam(p.team)}</div>
          <div className="prow__meta"><span className="prow__price num">{p.price} M€</span>
            {p.owner && <span className="prow__owner">de {p.owner}</span>}</div>
        </div>
      </div>

      <div className="ledger">
        <div><span>Tu saldo</span><b className="num">{r1(free)} M€</b></div>
        <div><span>Cláusula</span><b className="num" style={{ color: "var(--clause)" }}>−{p.clause} M€</b></div>
        <div className="ledger__total"><span>Te quedan</span><b className="num">{left} M€</b></div>
      </div>

      <p className="hint" style={{ marginTop: 12 }}>
        El dinero va entero a {p.owner ?? "su mánager"}. Al llegar a tu plantilla, el jugador
        queda blindado {lockH} h y su cláusula se recalcula.
      </p>

      <div className="sheet__actions">
        <button className="btn btn--clause btn--block btn--lg" disabled={busy || left < 0} onClick={onConfirm}>
          <IconBolt size={18} strokeWidth={2.2} />Confirmar clausulazo
        </button>
        <button className="btn btn--quiet btn--block" onClick={onClose}>Cancelar</button>
      </div>
    </Sheet>
  );
}

/* ------------------------------------------------- cómo se puntúa (reglas) */
const DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const hh = (h?: number) => `${String(h ?? 0).padStart(2, "0")}:00`;

/** Las reglas de la liga en cristiano: de dónde salen los puntos y qué se puede hacer cuándo. */
export function ScoringSheet({ lg, onClose }: { lg: any; onClose: () => void }) {
  const wb = lg.win_bonus ?? 0;
  return (
    <Sheet onClose={onClose} title="Cómo se puntúa">
      <div className="sheet__head" style={{ marginBottom: 6 }}>
        <div className="sheet__body">
          <h2>Cómo se puntúa</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            Jornada {lg.current_jornada} de {lg.max_jornada} · {lg.competition}
            {lg.grupo ? ` · ${lg.grupo}` : ""}
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      <div className="formula">
        <span className="formula__l">Puntos fantasy de un partido</span>
        <span className="formula__v">VAL <em>+ {wb} si su equipo gana + su +/- en pista</em></span>
      </div>

      <p className="hint">
        <b>VAL</b> es la valoración oficial de la FEB, tal cual sale en el acta:
        <br />
        (puntos + rebotes + asistencias + robos + tapones + faltas recibidas)
        <br />
        − (tiros fallados + pérdidas + tapones recibidos + faltas cometidas).
      </p>
      <p className="hint">
        El <b>+/- en pista</b> no se mira a secas, sino comparado con el marcador: si su
        equipo gana de 30 y él juega media hora, lo normal es acabar cerca de +22, así que
        quedarse en +1 resta. Y aguantar en positivo mientras el equipo pierde suma, aunque
        el resultado diga otra cosa. Mueve como mucho <b>±4,5 puntos</b> por partido, y a
        quien juega poco le cuenta menos.
      </p>
      <p className="hint">
        Cada jornada suman <b>solo tus {lg.lineup_size} titulares</b>. El banquillo no puntúa,
        pero verás lo que habría hecho. Un jugador que no juega hace 0 y uno que juega mal
        puede hacer negativos.
      </p>

      <Section>Calendario de la jornada</Section>
      <ol className="steps">
        <li>
          <b>Mercado</b>
          <span>Abre en cuanto acaba la jornada anterior y saca una tanda nueva cada día a
            las {hh(lg.market_hour)}. Se puja en secreto, se ficha por cláusula y se vende.</span>
        </li>
        <li>
          <b>Cierre · {fmtWhen(lg.market_deadline)}</b>
          <span>El mercado echa el cierre la noche antes del primer partido ({lg.market_close_before_h} h
            antes). A partir de ahí solo puedes cambiar el quinteto.</span>
        </li>
        <li>
          <b>Primer salto · {DAYS[lg.play_weekday ?? 5]} a las {hh(lg.play_hour)}</b>
          <span>Se cierra también el quinteto. Durante la jornada no se puede tocar nada.</span>
        </li>
        <li>
          <b>Fin de jornada</b>
          <span>Se puntúa sola en cuanto se han jugado todos los partidos. Si hay alguno
            aplazado, la liga espera a que se dispute: cuando llegue puntuará el quinteto
            que tenías al empezar la jornada, aunque alguno ya no sea tuyo.</span>
        </li>
      </ol>

      <Section>Precios</Section>
      <p className="hint">
        El precio de un jugador se mueve solo con lo que hace: mezcla su valoración media, su
        forma reciente y su +/−, ajustado por los partidos que lleva jugados. Su cláusula es
        ×{lg.clause_factor} ese valor.
      </p>
      {lg.sim_mode && (
        <p className="hint">
          Esta liga va en <b>modo simulación</b>: se juega la temporada{" "}
          {lg.season}/{String((Number(lg.season) + 1) % 100).padStart(2, "0")} jornada a jornada,
          así que solo ves las estadísticas hasta la jornada {lg.current_jornada}.
        </p>
      )}
    </Sheet>
  );
}

/* -------------------------------------- jornada de otro mánager (desglose) */
export function ManagerJornadaSheet({ row, onClose, onPlayer }: {
  row: any; onClose: () => void; onPlayer?: (id: number, jornada: number) => void;
}) {
  const players: any[] = row.players ?? [];
  // ver Table.tsx: en las jornadas viejas no se guardó el quinteto y no hay que fingirlo
  const known = row.lineup_known !== false;
  const starters = known ? players.filter((p) => p.starter) : [];
  const bench = known ? players.filter((p) => !p.starter) : [];
  const open = onPlayer ? (p: any) => onPlayer(p.player_id, row.jornada) : undefined;
  return (
    <Sheet onClose={onClose} title={row.manager}>
      <div className="sheet__head" style={{ marginBottom: 10 }}>
        <div className="sheet__body">
          <h2>{row.manager}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            Jornada {row.jornada} · {row.pos}º con {row.points} puntos
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>
      {!known && (
        <p className="hint" style={{ margin: "0 2px 10px" }}>
          Esta jornada se puntuó antes de que la liga guardara el quinteto: esto es su
          plantilla, no su alineación. Los {row.points} puntos son los de ese día.
        </p>
      )}
      {(known ? starters : players).map((p) => (
        <JornadaLine key={p.player_id} p={p} bench={!known} onOpen={open && (() => open(p))} />
      ))}
      {bench.length > 0 && <>
        <Section right="no suman">Banquillo</Section>
        {bench.map((p) => (
          <JornadaLine key={p.player_id} p={p} bench onOpen={open && (() => open(p))} />
        ))}
      </>}
    </Sheet>
  );
}

function JornadaLine({ p, bench, onOpen }: { p: any; bench?: boolean; onOpen?: () => void }) {
  return (
    <div className={"prow" + (bench ? " prow--dim" : "") + (onOpen ? " prow--tap" : "")}
      onClick={onOpen} tabIndex={onOpen ? 0 : undefined}
      onKeyDown={(e) => { if (onOpen && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen(); } }}>
      <Photo code={p.feb_code} name={p.name} variant="sm" />
      <div className="prow__body">
        <div className="prow__name">{prettyName(p.name)}</div>
        <div className="prow__team">
          {prettyTeam(p.team)}{p.gone ? " · ya no lo tiene" : ""}
        </div>
      </div>
      {p.played ? <PfBox value={p.points} muted={bench} />
        : <span className="dnp">{p.rests ? "Descansa" : "No jugó"}</span>}
    </div>
  );
}

/* ------------------------------------------- partidos de una jornada */
/**
 * Qué se juega (y qué falta) en una jornada. Es la respuesta visual a "¿por qué no se
 * ha puntuado todavía?": mientras quede un partido sin resultado la jornada sigue
 * abierta, y aquí se ve cuál es y cuándo se juega.
 */
export function MatchesSheet({ data, onClose }: { data: any; onClose: () => void }) {
  if (!data) return <Sheet onClose={onClose}><Loading label="Cargando partidos" /></Sheet>;
  const ms: any[] = data.matches ?? [];
  const faltan = ms.filter((m: any) => m.status !== "jugado");
  const movidos = ms.filter((m: any) => m.moved);

  return (
    <Sheet onClose={onClose} title={`Jornada ${data.jornada}`}>
      <div className="sheet__head" style={{ marginBottom: 12 }}>
        <div className="sheet__body">
          <h2>Jornada {data.jornada}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            {faltan.length === 0
              ? `${ms.length} partidos, todos jugados`
              : `Falta${faltan.length === 1 ? "" : "n"} ${faltan.length} de ${ms.length} por jugarse`}
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      {faltan.length > 0 && (
        <div className="notice notice--info" style={{ marginBottom: 12 }}>
          <span className="notice__ico"><IconClock size={18} /></span>
          <div>
            <b>La jornada no se puntúa hasta que acaben todos</b>
            <span>
              Así un aplazamiento no le cuela un cero a nadie: los puntos se reparten
              cuando entra el último resultado.
              {movidos.length > 0 && " Hay partidos con la fecha cambiada, marcados abajo."}
            </span>
          </div>
        </div>
      )}

      {ms.map((m: any) => <MatchRow key={m.match_id} m={m} />)}
      {ms.length === 0 && <p className="hint">Esta jornada todavía no tiene calendario.</p>}
    </Sheet>
  );
}

const ESTADO: Record<string, [string, string]> = {
  en_juego: ["En juego", "mstate--live"],
  pendiente: ["Por jugarse", "mstate--wait"],
  sin_resultado: ["Sin resultado", "mstate--warn"],
};

function MatchRow({ m }: { m: any }) {
  const jugado = m.home_score != null && m.away_score != null;
  const ganaLocal = jugado && m.home_score > m.away_score;
  const [txt, cls] = ESTADO[m.status] ?? ["", ""];
  return (
    <div className={"match" + (jugado ? "" : " match--open")}>
      <div className="match__when">
        <span>{fmtMatchDay(m.date, m.start_at)}</span>
        {m.moved === "aplazado" && <span className="mstate mstate--moved">Aplazado</span>}
        {m.moved === "adelantado" && <span className="mstate mstate--early">Adelantado</span>}
        {!jugado && txt && <span className={"mstate " + cls}>{txt}</span>}
      </div>
      <div className={"match__row" + (ganaLocal ? " is-win" : "")}>
        <span>{prettyTeam(m.home)}</span>
        <b className="num">{m.home_score ?? "–"}</b>
      </div>
      <div className={"match__row" + (jugado && !ganaLocal ? " is-win" : "")}>
        <span>{prettyTeam(m.away)}</span>
        <b className="num">{m.away_score ?? "–"}</b>
      </div>
    </div>
  );
}

/** "sáb 3 ene · 19:00" — con la hora solo si la FEB la ha publicado. */
export function fmtMatchDay(iso?: string | null, startAt?: string | null) {
  if (!iso && !startAt) return "Fecha por confirmar";
  const d = new Date(startAt ?? `${iso}T12:00:00Z`);
  const dia = d.toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
  if (!startAt) return dia;
  const h = d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  return `${dia} · ${h}`;
}


/** Próximo partido del jugador: rival, dónde y cuándo. */
function NextMatch({ n }: { n: any }) {
  return (
    <div className={"nextmatch" + (n.rests_now ? " nextmatch--rest" : "")}>
      <span className="nextmatch__k">
        {n.rests_now ? `Descansa · vuelve en la J${n.jornada}` : `Jornada ${n.jornada}`}
      </span>
      <div className="nextmatch__v">
        <span className="nextmatch__vs">{n.home ? "vs" : "@"}</span>
        {prettyTeam(n.rival)}
      </div>
      <span className="nextmatch__when">
        {n.home ? "En casa" : "Fuera"} · {fmtMatchDay(n.date, n.start_at)}
      </span>
    </div>
  );
}

/* --------------------------------------------------- aviso de descansos */
/**
 * Salta solo, y solo mientras aún se puede arreglar: durante la semana de mercado y en
 * el último cambio de quinteto. Un jugador que descansa suma cero y no hay forma de
 * saberlo mirando su ficha, así que no vale con dejarlo escrito en la pantalla del
 * equipo: hay que ponerlo delante. Una vez por jornada; luego se calla.
 */
export function RestSheet({ jugadores, jornada, onClose, onFix }: {
  jugadores: any[]; jornada: number; onClose: () => void; onFix: () => void;
}) {
  const uno = jugadores.length === 1;
  return (
    <Sheet onClose={onClose} title="Descansos de la jornada">
      <div className="sheet__head">
        <span className="sheet__ico"><IconCalendar size={22} /></span>
        <div className="sheet__body">
          <h2>{uno ? "Uno de tu quinteto descansa" : `${jugadores.length} de tu quinteto descansan`}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            En la jornada {jornada} {uno ? "su equipo no juega" : "sus equipos no juegan"}
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      {jugadores.map((p) => (
        <div key={p.player_id} className="prow">
          <Photo code={p.feb_code} name={p.name} variant="sm" />
          <div className="prow__body">
            <div className="prow__name">{prettyName(p.name)}</div>
            <div className="prow__team">{prettyTeam(p.team)}</div>
          </div>
          <span className="dnp">Descansa</span>
        </div>
      ))}

      <p className="hint" style={{ marginTop: 12 }}>
        La conferencia tiene un número impar de equipos, así que cada jornada descansa uno.
        {uno ? " Sumará" : " Sumarán"} 0 puntos aunque {uno ? "esté" : "estén"} en el
        quinteto: cámbia{uno ? "lo" : "los"} por alguien del banquillo mientras puedas.
      </p>

      <button className="btn btn--block btn--lg" style={{ marginTop: 14 }} onClick={onFix}>
        <IconSquad size={17} />Ir al quinteto
      </button>
      <button className="btn btn--quiet btn--block" style={{ marginTop: 8 }} onClick={onClose}>
        Ya lo sé, dejarlo así
      </button>
    </Sheet>
  );
}

/* ------------------------------------------------------ invitar a la liga */
/**
 * El código suelto no invita a nadie: hay que copiarlo, abrir WhatsApp, explicar dónde
 * se mete... Aquí se comparte un enlace que ya lleva el código dentro, así que quien lo
 * reciba solo tiene que tocarlo y ponerse el nombre de mánager.
 */
export function InviteSheet({ lg, onClose, onCopied }: {
  lg: any; onClose: () => void; onCopied: (msg: string) => void;
}) {
  const enlace = `${window.location.origin}/?join=${lg.join_code}`;
  const texto = `Te invito a mi liga de PiFantasy, "${lg.name}".\n\n`
    + `Entra aquí y ya te sale el código puesto:\n${enlace}\n\n`
    + `(o métete en ${window.location.host} y pon el código ${lg.join_code})`;

  const copiar = async (qué: string, aviso: string) => {
    try {
      await navigator.clipboard.writeText(qué);
      onCopied(aviso);
    } catch {
      onCopied("No se pudo copiar; mantén pulsado el código para copiarlo a mano");
    }
  };

  const compartir = async () => {
    try {
      await navigator.share({ title: `Liga ${lg.name} · PiFantasy`, text: texto });
    } catch { /* el usuario ha cancelado: no es un error */ }
  };

  return (
    <Sheet onClose={onClose} title="Invitar">
      <div className="sheet__head" style={{ marginBottom: 14 }}>
        <div className="sheet__body">
          <h2>Invita a tu liga</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>{lg.name}</div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      <button className="joincode" onClick={() => copiar(lg.join_code, "Código copiado")}>
        <span className="joincode__k">Código de la liga · toca para copiar</span>
        <span className="joincode__v num">{lg.join_code}</span>
      </button>

      <div className="sheet__actions">
        {typeof navigator.share === "function" && (
          <button className="btn btn--block btn--lg" onClick={compartir}>
            <IconShare size={18} />Compartir por WhatsApp…
          </button>
        )}
        <a className="btn btn--ghost btn--block"
          href={`https://wa.me/?text=${encodeURIComponent(texto)}`}
          target="_blank" rel="noreferrer">
          <IconWhatsApp size={18} />Abrir WhatsApp
        </a>
        <button className="btn btn--quiet btn--block"
          onClick={() => copiar(enlace, "Enlace copiado")}>
          <IconCopy size={17} />Copiar el enlace
        </button>
      </div>

      <p className="hint" style={{ marginTop: 14 }}>
        Quien toque el enlace entra directo a unirse, con el código ya puesto: solo tiene
        que elegir su nombre de mánager. El código no caduca y sirve para todos.
      </p>
    </Sheet>
  );
}


/* ------------------------------------------------ oferta a otro mánager */
/**
 * Ofrecer por el jugador de otro. A diferencia del clausulazo, aquí él decide: por eso
 * se puede ofrecer lo que se quiera, no hay un precio impuesto.
 */
export function OfferSheet({ p, free, busy, onClose, onSend }: {
  p: any; free: number; busy?: boolean; onClose: () => void; onSend: (n: number) => void;
}) {
  const valor = p.price ?? 0;
  const [amount, setAmount] = useState<number>(r1(valor * 1.1));
  const max = r1(free);
  const paso = (d: number) => setAmount((a) => Math.max(0.5, Math.min(max, r1(a + d))));
  const vale = amount > 0 && amount <= max + 1e-6;
  const dif = r1(amount - valor);

  return (
    <Sheet onClose={onClose} title="Hacer una oferta">
      <div className="sheet__head">
        <Photo code={p.feb_code} name={p.name} />
        <div className="sheet__body">
          <h2 style={{ fontSize: "var(--fs-lg)" }}>{fullName(p.name)}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>{prettyTeam(p.team)}</div>
          <div className="chiprow" style={{ marginTop: 6 }}>
            <span className="chip chip--accent">Vale <b>{valor}</b> M€</span>
            {p.owner && <span className="chip">de {p.owner}</span>}
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      <div className="stepper">
        <button className="stepper__btn" aria-label="Bajar" onClick={() => paso(-0.5)}>
          <IconMinus size={20} /></button>
        <input type="number" step="0.1" value={amount} inputMode="decimal"
          onChange={(e) => setAmount(Number(e.target.value))} />
        <button className="stepper__btn" aria-label="Subir" onClick={() => paso(0.5)}>
          <IconPlus size={20} /></button>
      </div>
      <div className="quick">
        {[0, 10, 25, 50].map((pct) => (
          <button key={pct} onClick={() => setAmount(Math.min(max, r1(valor * (1 + pct / 100))))}>
            {pct === 0 ? "Su valor" : `+${pct}%`}
          </button>
        ))}
      </div>

      <p className="hint" style={{ margin: "12px 0 0" }}>
        {dif >= 0
          ? <>Ofreces <b>{Math.abs(dif)} M€ más</b> de lo que vale.</>
          : <>Ofreces <b>{Math.abs(dif)} M€ menos</b> de lo que vale; con eso es fácil que
              te diga que no.</>}{" "}
        Puedes llegar hasta <b>{max} M€</b>. Mientras no responda, ese dinero queda
        apalabrado y no puedes gastarlo en otra cosa.
      </p>

      <div className="sheet__actions">
        <button className="btn btn--block btn--lg" disabled={!vale || busy}
          onClick={() => onSend(amount)}>
          <IconCoin size={18} />Enviar oferta · {amount} M€
        </button>
        <button className="btn btn--quiet btn--block" onClick={onClose}>Cancelar</button>
      </div>
    </Sheet>
  );
}


/* ------------------------------------------------------- cambiar el quinteto */
/* Arrastrar es el gesto que la gente ya trae aprendido de cualquier fantasy, así que la
   pista es el tablero y el banquillo el cajón. Pero arrastrar en un móvil falla —dedos
   gordos, scroll que se cuela— así que el toque hace lo mismo: tocas al jugador, tocas el
   hueco. Ninguna de las dos vías es la "de verdad": las dos lo son. */

const SLOTS = [
  { left: "50%", top: "80%" }, { left: "17%", top: "63%" }, { left: "83%", top: "63%" },
  { left: "30%", top: "35%" }, { left: "70%", top: "31%" },
];

type Hueco = any | null;

export function LineupSheet({ squad, lineupSize, busy, onClose, onSave }: {
  squad: any[]; lineupSize: number; busy?: boolean;
  onClose: () => void; onSave: (ids: number[]) => void;
}) {
  // Pista y banquillo son un solo reparto, y por eso viven en un solo estado. Tenerlos en
  // dos `useState` obligaba a actualizar uno dentro del updater del otro, y eso React no lo
  // admite: el updater tiene que ser puro. En StrictMode corre dos veces y el resultado era
  // que el jugador desalojado no bajaba al banquillo, o se perdía por el camino.
  const inicial = () => {
    const t = squad.filter((p: any) => p.starter).slice(0, lineupSize);
    return {
      huecos: Array.from({ length: lineupSize }, (_, i) => t[i] ?? null) as Hueco[],
      banquillo: squad.filter((p: any) => !p.starter) as any[],
    };
  };
  const [reparto, setReparto] = useState(inicial);
  const { huecos, banquillo } = reparto;
  const [cogido, setCogido] = useState<any | null>(null);   // seleccionado al toque
  const [fantasma, setFantasma] = useState<{ p: any; x: number; y: number } | null>(null);

  /* ---- mover una ficha de donde esté al destino pedido ---- */
  function colocar(p: any, destino: number | "banquillo") {
    setReparto(({ huecos: hs, banquillo: bq }) => {
      const h = [...hs];
      // Se le saca de donde estuviera, sea la pista o el banquillo...
      const desde = h.findIndex((x) => x?.player_id === p.player_id);
      if (desde >= 0) h[desde] = null;
      let b = bq.filter((x: any) => x.player_id !== p.player_id);

      if (destino === "banquillo") {
        b = [p, ...b];
      } else {
        // ...y si el hueco estaba ocupado, el que sale baja al banquillo. Nadie se evapora:
        // cada jugador está siempre o en la pista o en el banquillo.
        const desalojado = h[destino];
        if (desalojado) b = [desalojado, ...b];
        h[destino] = p;
      }
      return { huecos: h, banquillo: b };
    });
    setCogido(null);
  }

  /* ---- gestos ----------------------------------------------------------------
     Sin `setPointerCapture` y sin depender de `click`. La captura redirige los eventos
     siguientes al elemento capturado, así que el segundo toque —el del hueco— le llegaba
     a la ficha del jugador y no al hueco. Y el `click` de un táctil se pierde en cuanto el
     dedo se desplaza un poco. Aquí todo sale de `pointerdown` + `pointerup` en window, que
     es lo único que un móvil entrega siempre.                                          */
  const [gesto, setGesto] = useState<
    { tipo: "jugador"; p: any; x0: number; y0: number }
    | { tipo: "hueco"; i: number; x0: number; y0: number } | null>(null);
  const movido = useRef(false);
  const [quieta, setQuieta] = useState(false);
  useEffect(() => { const t = setTimeout(() => setQuieta(true), 300); return () => clearTimeout(t); }, []);

  useEffect(() => {
    if (!gesto) return;

    const alMover = (e: PointerEvent) => {
      if (!movido.current && Math.hypot(e.clientX - gesto.x0, e.clientY - gesto.y0) < 12) return;
      movido.current = true;
      if (gesto.tipo === "jugador") setFantasma({ p: gesto.p, x: e.clientX, y: e.clientY });
    };

    const alSoltar = (e: PointerEvent) => {
      const arrastrado = movido.current;
      const bajo = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const diana = bajo?.closest("[data-destino]") as HTMLElement | null;
      const d = diana?.dataset.destino;
      const destino: number | "banquillo" | null =
        d == null ? null : d === "banquillo" ? "banquillo" : Number(d);

      if (gesto.tipo === "hueco") {
        // Un hueco vacío no hace nada por sí solo; solo recibe al que llevas cogido.
        if (cogido) colocar(cogido, gesto.i);
      } else {
        const p = gesto.p;
        const enPista = huecos.findIndex((h: any) => h?.player_id === p.player_id);
        const suSitio: number | "banquillo" = enPista >= 0 ? enPista : "banquillo";

        if (arrastrado && destino !== null && destino !== suSitio) {
          colocar(p, destino);                       // arrastre de verdad
        } else if (cogido && cogido.player_id !== p.player_id) {
          // Llevas a uno cogido y tocas a otro: se cambian el sitio.
          colocar(cogido, suSitio);
        } else {
          setCogido((c: any) => (c?.player_id === p.player_id ? null : p));
        }
      }

      movido.current = false;
      setGesto(null);
      setFantasma(null);
    };

    const alCancelar = () => { movido.current = false; setGesto(null); setFantasma(null); };

    window.addEventListener("pointermove", alMover);
    window.addEventListener("pointerup", alSoltar);
    window.addEventListener("pointercancel", alCancelar);
    return () => {
      window.removeEventListener("pointermove", alMover);
      window.removeEventListener("pointerup", alSoltar);
      window.removeEventListener("pointercancel", alCancelar);
    };
  }, [gesto, cogido, reparto]);   // eslint-disable-line react-hooks/exhaustive-deps

  const cogerJugador = (p: any) => ({
    onPointerDown: (e: React.PointerEvent) => {
      if (busy) return;
      e.stopPropagation();      // que no lo tome también el hueco de debajo
      movido.current = false;
      setGesto({ tipo: "jugador", p, x0: e.clientX, y0: e.clientY });
    },
  });
  const cogerHueco = (i: number) => ({
    onPointerDown: (e: React.PointerEvent) => {
      if (busy) return;
      movido.current = false;
      setGesto({ tipo: "hueco", i, x0: e.clientX, y0: e.clientY });
    },
  });

  const puestos = huecos.filter(Boolean).length;
  const idsAhora = huecos.filter(Boolean).map((h: any) => h.player_id).sort().join(",");
  const idsAlAbrir = squad.filter((p: any) => p.starter).map((p: any) => p.player_id)
    .sort().join(",");
  const sinCambios = idsAhora === idsAlAbrir;

  return (
    <Sheet onClose={onClose} title="Cambiar quinteto">
      <div className="sheet__head">
        <span className="sheet__ico"><IconSquad size={22} /></span>
        <div className="sheet__body">
          <h2>Cambiar quinteto</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            Arrastra a la pista, o toca al jugador y luego el hueco
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      <div className={"lu__court" + (quieta ? " lu--anima" : "")}>
        <HalfCourt />
        {SLOTS.slice(0, lineupSize).map((pos, i) => {
          const p = huecos[i];
          const libre = !p;
          return (
            <div key={i} data-destino={i} style={pos as any} {...cogerHueco(i)}
              className={"lu__slot" + (libre ? " lu__slot--free" : "")
                + (cogido && libre ? " lu__slot--target" : "")}>
              {p
                ? <div key={p.player_id} {...cogerJugador(p)}
                    className={"lu__tok" + (cogido?.player_id === p.player_id ? " is-held" : "")}>
                    <Photo code={p.feb_code} name={p.name} variant="tok" />
                    <span className="lu__tag">{prettyName(p.name).split(" ").slice(-1)[0]}</span>
                  </div>
                : <div className="lu__empty"><IconPlus size={17} /></div>}
            </div>
          );
        })}
      </div>

      <div className="lu__count">
        <b className="num">{puestos}</b> de {lineupSize} puestos
        {puestos < lineupSize && <span> · arrastra {lineupSize - puestos} más</span>}
      </div>

      <Section right={String(banquillo.length)}>Banquillo</Section>
      <div className={"lu__bench" + (quieta ? " lu--anima" : "")} data-destino="banquillo">
        {banquillo.length === 0 && <p className="hint">No te queda nadie en el banquillo.</p>}
        {banquillo.map((p) => (
          <div key={p.player_id} {...cogerJugador(p)}
            className={"lu__card" + (cogido?.player_id === p.player_id ? " is-held" : "")
              + (p.departed ? " lu__card--gone" : "")}>
            <Photo code={p.feb_code} name={p.name} variant="sm" />
            <div className="lu__card__b">
              <div className="lu__card__n">{prettyName(p.name)}</div>
              <div className="lu__card__t">{prettyTeam(p.team)}</div>
            </div>
            <PfBox value={fp(p)} muted={p.departed} />
          </div>
        ))}
      </div>

      <div className="sheet__actions">
        <button className="btn" disabled={busy || sinCambios}
          onClick={() => onSave(huecos.filter(Boolean).map((p: any) => p.player_id))}>
          {busy ? <span className="spinner" /> : sinCambios ? "Sin cambios" : "Guardar quinteto"}
        </button>
      </div>

      {fantasma && (
        <div className="lu__ghost" style={{ left: fantasma.x, top: fantasma.y }}>
          <Photo code={fantasma.p.feb_code} name={fantasma.p.name} variant="tok" />
        </div>
      )}
    </Sheet>
  );
}
