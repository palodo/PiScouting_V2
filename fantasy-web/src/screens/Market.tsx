/* ============================================================================
   Mercado: subastas de la tanda del día y escaparate de cláusulas (clausulazos).
   ========================================================================== */
import { useMemo, useState } from "react";
import { IconBolt, IconClose, IconLock, IconMarket, IconPlay, IconSearch } from "../icons";
import { PlayerRow, fp, lockLabel } from "../parts";
import { Empty, Segmented, SkeletonList, fmtWhen, useNow } from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

export default function MarketTab({
  lg, market, clauses, admin, busy, closes, opens, view, onView,
  onOpenPlayer, onBid, onClause, onForceOpen, onForceClose,
}: any) {
  return (
    <>
      <MarketHead lg={lg} market={market} admin={admin} busy={busy} closes={closes} opens={opens}
        onForceOpen={onForceOpen} onForceClose={onForceClose} />

      <div style={{ margin: "12px 0" }}>
        <Segmented value={view} onChange={onView} options={[
          { v: "subastas", label: "Subastas" },
          { v: "clausulas", label: "Cláusulas" },
        ]} />
      </div>

      {view === "subastas"
        ? <Auctions lg={lg} market={market} busy={busy} onOpenPlayer={onOpenPlayer} onBid={onBid} />
        : <Clauses data={clauses} busy={busy} onOpenPlayer={onOpenPlayer} onClause={onClause} />}
    </>
  );
}

/* ------------------------------------------------------------ cuenta atrás */
function MarketHead({ lg, market, admin, busy, closes, opens, onForceOpen, onForceClose }: any) {
  const now = useNow(5000);
  const from = market?.opens_at ?? lg.market_opens_at;
  const to = market?.closes_at ?? lg.market_closes_at;
  let left = 100;
  if (lg.market_open && from && to) {
    const a = new Date(from).getTime(), b = new Date(to).getTime();
    left = Math.min(100, Math.max(0, 100 - ((now - a) / (b - a)) * 100));
  }
  return (
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
      {lg.market_open && <div className="progress"><div className="progress__fill" style={{ width: `${left}%` }} /></div>}
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
  );
}

/* ----------------------------------------------------------------- subastas */
function Auctions({ lg, market, busy, onOpenPlayer, onBid }: any) {
  if (!lg.market_open) {
    return (
      <Empty icon={<IconMarket size={22} />} title="El mercado está cerrado">
        Vuelve cuando abra para pujar. Mientras tanto puedes ir de clausulazo.
      </Empty>
    );
  }
  if (!market) return <SkeletonList n={5} />;
  if (!market.listings.length) return <Empty icon={<IconMarket size={22} />} title="No hay jugadores en esta tanda" />;

  const committed = market.committed ?? 0;
  const free = r1((market.my_budget ?? 0) - committed);

  return (
    <>
      {committed > 0 && (
        <div className="budget">
          <div>
            <div className="budget__k">Libre</div>
            <div className="budget__n">{free} M€</div>
          </div>
          <div className="budget__bar">
            <div className="budget__used"
              style={{ width: `${Math.min(100, (committed / Math.max(1, market.my_budget)) * 100)}%` }} />
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="budget__k">En pujas</div>
            <div className="budget__n" style={{ color: "var(--clause)" }}>{r1(committed)} M€</div>
          </div>
        </div>
      )}

      {market.listings.map((l: any) => (
        <PlayerRow key={l.listing_id} p={l} onOpen={() => onOpenPlayer(l.player_id)}
          tone={l.my_bid != null ? "bid" : undefined}
          right={
            <button className={"btn btn--sm" + (l.my_bid != null ? " btn--pos" : "")} disabled={busy}
              onClick={(e) => { e.stopPropagation(); onBid(l); }}>
              {l.my_bid != null ? `Puja ${l.my_bid}` : "Pujar"}
            </button>
          } />
      ))}
    </>
  );
}

/* ---------------------------------------------------------------- cláusulas */
type Filter = "todos" | "puedo" | "libres";

function Clauses({ data, busy, onOpenPlayer, onClause }: any) {
  const [filter, setFilter] = useState<Filter>("todos");
  const [q, setQ] = useState("");
  const free = data ? r1((data.my_budget ?? 0) - (data.committed ?? 0)) : 0;

  const list = useMemo(() => {
    const all: any[] = (data?.players ?? []).filter((p: any) => !p.mine);
    const needle = q.trim().toLowerCase();
    return all.filter((p) => {
      if (filter === "puedo" && (p.clause > free || p.clause_locked)) return false;
      if (filter === "libres" && p.clause_locked) return false;
      if (needle && !`${p.name} ${p.team} ${p.owner}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [data, filter, free, q]);

  if (!data) return <SkeletonList n={6} />;

  return (
    <>
      <div className="clausebar">
        <span style={{ color: "var(--clause)" }}><IconBolt size={19} strokeWidth={2} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="budget__k">Puedes gastar</div>
          <div className="budget__n" style={{ fontSize: "var(--fs-lg)" }}>{free} M€</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="budget__k">A tiro</div>
          <div className="budget__n" style={{ fontSize: "var(--fs-lg)", color: "var(--clause)" }}>
            {(data.players ?? []).filter((p: any) => !p.mine && !p.clause_locked && p.clause <= free).length}
          </div>
        </div>
      </div>

      <div className="searchbox">
        <IconSearch size={17} />
        <input className="searchbox__in" placeholder="Buscar jugador, equipo o mánager"
          value={q} onChange={(e) => setQ(e.target.value)} />
        {q && <button className="iconbtn" onClick={() => setQ("")} aria-label="Limpiar"><IconClose size={16} /></button>}
      </div>

      <div className="filters">
        {([["todos", "Todos"], ["puedo", "Puedo pagarla"], ["libres", "Sin blindar"]] as [Filter, string][])
          .map(([v, label]) => (
            <button key={v} className={"filter" + (filter === v ? " is-on" : "")} onClick={() => setFilter(v)}>
              {label}
            </button>
          ))}
      </div>

      {list.length === 0
        ? <Empty icon={<IconBolt size={22} />} title="Nada por aquí">
            Prueba a quitar filtros: quizá aún no hay jugadores con cláusula a tu alcance.
          </Empty>
        : list.map((p: any) => {
          const afford = p.clause <= free;
          return (
            <PlayerRow key={p.player_id} p={p} onOpen={() => onOpenPlayer(p.player_id)}
              meta={<>
                <span className="prow__pf num">{fp(p).toFixed(1)} PF</span>
                <span className="prow__owner">{p.owner}</span>
              </>}
              hero={<div className="claim">
                <span className="claim__v num">{p.clause}</span>
                <span className="claim__u">M€ cláusula</span>
              </div>}
              right={
                p.clause_locked
                  ? <span className="lockchip"><IconLock size={11} strokeWidth={2.4} />{lockLabel(p.clause_lock_mins)}</span>
                  : <button className={"btn btn--sm " + (afford ? "btn--clause" : "btn--quiet")}
                      disabled={busy || !afford}
                      onClick={(e) => { e.stopPropagation(); onClause(p); }}>
                      <IconBolt size={13} strokeWidth={2.2} />{afford ? "Pagar" : "No llegas"}
                    </button>
              } />
          );
        })}

      <p className="hint" style={{ marginTop: 14 }}>
        Pagar la cláusula te lleva al jugador al instante y el dinero va entero a su mánager.
        Al llegar a tu plantilla queda blindado {data.clause_lock_h} h.
      </p>
    </>
  );
}
