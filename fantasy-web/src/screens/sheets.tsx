/* ============================================================================
   Hojas inferiores: ficha del jugador, puja y plantilla de un rival.
   ========================================================================== */
import { useEffect, useState } from "react";
import { api } from "../api";
import { IconBolt, IconCheck, IconClose, IconGavel, IconLock, IconMinus, IconPlus } from "../icons";
import { PfBox, PlayerRow, lockLabel } from "../parts";
import { Loading, Photo, Section, Sheet, SheetClose, prettyName, prettyTeam } from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

/* ---------------------------------------------------------- ficha completa */
export function PlayerSheet({ leagueId, playerId, league, myMemberId, freeBudget, busy,
  onClose, onClause, onRaise, onSell }: any) {
  const [d, setD] = useState<any>(null);
  const [mode, setMode] = useState<"view" | "raise" | "sell">("view");
  const [newClause, setNewClause] = useState(0);

  useEffect(() => {
    setD(null); setMode("view");
    api.player(leagueId, playerId).then((x) => {
      setD(x);
      setNewClause(r1((x.clause ?? 0) + 10));
    }).catch(() => setD(false));
  }, [leagueId, playerId]);

  if (d === false) {
    return <Sheet onClose={onClose}><div className="empty"><b>No se pudo cargar la ficha</b></div></Sheet>;
  }
  if (!d) return <Sheet onClose={onClose}><Loading label="Cargando ficha" /></Sheet>;

  const wb = d.win_bonus ?? league?.win_bonus ?? 0;
  const games: any[] = d.last ?? [];
  const gamePts = (g: any) => r1(g.val + (g.won ? wb : 0));
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

  return (
    <Sheet onClose={onClose} title={prettyName(d.name)}>
      <div className="sheet__head">
        <Photo code={d.feb_code} name={d.name} variant="lg" />
        <div className="sheet__body">
          <h2>{prettyName(d.name)}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>{prettyTeam(d.team)}</div>
          <div className="chiprow" style={{ marginTop: 7 }}>
            <span className="chip chip--accent"><b>{d.price}</b> M€</span>
            <span className="chip">{d.games} PJ</span>
            <span className="chip">{d.wins}V · {d.losses}D</span>
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      {/* Lo que de verdad suma en la liga */}
      <div className="fp">
        <div>
          <span className="fp__k">Puntos fantasy · media</span>
          <span className="fp__v num">{fpAvg}</span>
          <span className="fp__note">VAL {d.avg.val} + {wb} por victoria de su equipo</span>
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
        {rival && (
          <button className="btn btn--clause btn--block" disabled={busy || d.clause_locked || d.clause > freeBudget}
            onClick={() => onClause(d)}>
            <IconBolt size={17} strokeWidth={2.2} />
            {d.clause_locked ? "Blindado ahora mismo"
              : d.clause > freeBudget ? `Te faltan ${r1(d.clause - freeBudget)} M€`
                : `Pagar cláusula · ${d.clause} M€`}
          </button>
        )}

        {mine && mode === "view" && (
          <>
            <button className="btn btn--ghost btn--block" onClick={() => setMode("raise")}>
              <IconLock size={17} />Subir cláusula
            </button>
            <button className="btn btn--danger btn--block" onClick={() => setMode("sell")}>
              Vender por {d.price} M€
            </button>
          </>
        )}

        {mine && mode === "sell" && (
          <>
            <p className="hint" style={{ margin: 0 }}>
              Se vende al precio de mercado de hoy: <b>{d.price} M€</b> al saldo. No se puede deshacer.
            </p>
            <button className="btn btn--danger btn--block" disabled={busy}
              onClick={() => onSell(d.player_id)}>
              <IconCheck size={17} />Confirmar venta
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
          <h2 style={{ fontSize: "var(--fs-lg)" }}>{prettyName(listing.name)}</h2>
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
export function ManagerSheet({ data, free, onClose, onPlayer, onClause }: {
  data: any; free: number; onClose: () => void;
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
        Paga la cláusula y te lo llevas al momento. Tienes <b>{r1(free)} M€</b> libres.
      </p>
      <div>
        {data.squad.map((p: any) => (
          <PlayerRow key={p.player_id} p={p} onOpen={() => onPlayer(p.player_id)}
            tone={p.starter ? "starter" : undefined}
            right={p.clause_locked
              ? <span className="lockchip"><IconLock size={11} strokeWidth={2.4} />{lockLabel(p.clause_lock_mins)}</span>
              : <button className={"btn btn--sm " + (p.clause <= free ? "btn--clause" : "btn--quiet")}
                  disabled={p.clause > free}
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

/* -------------------------------------- jornada de otro mánager (desglose) */
export function ManagerJornadaSheet({ row, onClose }: { row: any; onClose: () => void }) {
  const players: any[] = row.players ?? [];
  const starters = players.filter((p) => p.starter);
  const bench = players.filter((p) => !p.starter);
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
      {starters.map((p) => <JornadaLine key={p.player_id} p={p} />)}
      {bench.length > 0 && <>
        <Section right="no suman">Banquillo</Section>
        {bench.map((p) => <JornadaLine key={p.player_id} p={p} bench />)}
      </>}
    </Sheet>
  );
}

function JornadaLine({ p, bench }: { p: any; bench?: boolean }) {
  return (
    <div className={"prow" + (bench ? " prow--dim" : "")}>
      <Photo code={p.feb_code} name={p.name} variant="sm" />
      <div className="prow__body">
        <div className="prow__name">{prettyName(p.name)}</div>
        <div className="prow__team">{prettyTeam(p.team)}</div>
      </div>
      {p.played ? <PfBox value={p.points} muted={bench} /> : <span className="dnp">No jugó</span>}
    </div>
  );
}
