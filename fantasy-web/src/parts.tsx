/* ============================================================================
   Piezas compartidas entre pantallas: la fila de jugador (mercado, plantilla y
   plantilla del rival) y la fila del feed.
   ========================================================================== */
import type { ReactNode } from "react";
import { FEED_ICON, IconBolt, IconCalendar, IconGavel, IconInfo, IconLock, IconTrendUp } from "./icons";
import { Photo, Trend, fmtWhen, prettyName, prettyTeam, relTime, stripEmoji } from "./ui";

export type RowPlayer = {
  player_id: number;
  name: string;
  feb_code?: string | null;
  team?: string | null;
  price: number;
  fp_avg?: number;
  fp_form?: number;
  /** Jornada en juego: `live_fp` es lo que lleva hoy, o null si aún no ha jugado. */
  live?: boolean;
  live_fp?: number | null;
  val_avg?: number;
  form?: number;
  delta?: number;
  starter?: boolean;
  departed?: boolean;
  /** su equipo no juega esta jornada (conferencia con equipos impares) */
  rests?: boolean;
  clause?: number | null;
  clause_locked?: boolean;
  clause_lock_mins?: number;
  bids?: number;
  my_bid?: number | null;
};

/** Puntos fantasy: el dato que de verdad suma. Si el backend es antiguo, VAL. */
export const fp = (p: { fp_avg?: number; val_avg?: number }) => p.fp_avg ?? p.val_avg ?? 0;
export const fpForm = (p: { fp_form?: number; form?: number }) => p.fp_form ?? p.form ?? 0;

/* --------------------------------------------------------------- fase de la liga */
export type Phase = "mercado" | "alineacion" | "jornada" | "fin";

/**
 * En qué momento de la jornada está la liga. Una sola fuente para la cabecera, el mercado
 * y el equipo, para que los tres cuenten lo mismo. El backend manda `phase`; si respondiera
 * uno antiguo (sin fases), se cae al comportamiento de siempre: mercado abierto o cerrado.
 */
export function phaseInfo(lg: any) {
  const phase: Phase = lg?.phase ?? "mercado";
  const j = lg?.next_jornada ?? (lg?.current_jornada ?? 0) + 1;
  if (phase === "fin") {
    return { phase, j, chip: "Temporada completa", title: "Temporada completa", until: null,
      note: "Ya no quedan jornadas por jugar.", live: false };
  }
  if (phase === "jornada") {
    const pend: string[] = lg?.pending_matches ?? [];
    const sim = lg?.sim;
    // En simulación no hay reloj de verdad, así que el contador honesto son los partidos
    // disputados: un cronómetro inventado diría una hora que no significa nada.
    if (sim) {
      return {
        phase, j, chip: `${sim.played}/${sim.total} partidos`,
        title: `Jornada ${j} en juego`, until: null, live: true,
        note: sim.played === 0
          ? "Mercado cerrado y quintetos bloqueados. Aún no se ha jugado nada."
          : `Van ${sim.played} de ${sim.total} partidos. Los puntos que ves son provisionales.`,
      };
    }
    return {
      phase, j, chip: `J${j} en juego`, title: `Jornada ${j} en juego · acaba en`,
      until: lg?.jornada_ends_at ?? null, live: true,
      note: pend.length
        ? `Falta por disputarse ${pend[0]}${pend.length > 1 ? ` y ${pend.length - 1} más` : ""}.`
        : "Mientras se juega no se ficha ni se toca el quinteto.",
    };
  }
  if (phase === "alineacion") {
    return {
      phase, j, chip: "Último cambio", title: `Jornada ${j} · empieza en`,
      until: lg?.kickoff_at ?? null, live: false,
      note: "Mercado cerrado. Puedes cambiar el quinteto hasta el primer partido.",
    };
  }
  return {
    phase, j, chip: lg?.market_open ? "Mercado" : "Mercado cerrado",
    title: lg?.market_open ? "Mercado abierto · tanda nueva en" : "Mercado · abre en",
    until: lg?.market_open ? (lg?.market_closes_at ?? null) : (lg?.market_opens_at ?? null),
    live: Boolean(lg?.market_open),
    // el día y la hora concretos: "hasta 24 h antes" obliga a hacer la cuenta
    note: `Se ficha hasta ${fmtWhen(lg?.market_deadline)}, y luego solo se toca el quinteto.`,
  };
}

export function lockLabel(mins?: number) {
  if (!mins || mins <= 0) return "";
  const h = Math.floor(mins / 60);
  return h > 0 ? `${h} h` : `${mins} min`;
}

/**
 * El número que decide la liga, en grande y aislado del resto. `muted` lo pinta apagado
 * (banquillo, jugador que ya no puntúa) pero SIGUE enseñando sus puntos: saber que el
 * suplente hizo 21 es justo lo que duele —y lo que te hace cambiar el quinteto.
 */
export function PfBox({ value, muted, label = "PF" }: { value: number; muted?: boolean; label?: string }) {
  return (
    <div className={"pfbox" + (muted ? " pfbox--muted" : "")}>
      <b className="num">{value.toFixed(1)}</b>
      <span>{label}</span>
    </div>
  );
}

/** Lo que cuesta. En el mercado es el dato que manda, así que va en la caja grande. */
export function PriceBox({ value }: { value: number }) {
  return (
    <div className="pricebox">
      {/* siempre con decimal: en una columna de precios, "18" junto a "17.8" baila */}
      <b className="num">{value.toFixed(1)}</b>
      <span>M€</span>
    </div>
  );
}

/**
 * Fila de jugador. A la izquierda quién es y cuánto vale; a la derecha, aislados,
 * los puntos fantasy. Las medias de valoración y demás se han bajado a la ficha:
 * de un vistazo solo debe competir un número.
 */
export function PlayerRow({ p, onOpen, right, tone, meta, hero, hidePrice, pf: pfValue }: {
  p: RowPlayer;
  onOpen?: () => void;
  right?: ReactNode;
  tone?: "starter" | "bid" | "gone";
  meta?: ReactNode;
  /** Sustituye la caja de PF cuando la pantalla va de otra cosa (p. ej. cláusulas). */
  hero?: ReactNode;
  /** Cuando el precio ya va en la caja grande, no se repite en la línea de datos. */
  hidePrice?: boolean;
  pf?: number;
}) {
  const cls = ["prow", onOpen ? "prow--tap" : "", tone ? `prow--${tone}` : ""].join(" ").trim();
  // Sin role="button": la fila lleva dentro botones de verdad (pujar, alinear) y anidar
  // controles rompe la navegación por lector de pantalla. Sigue siendo enfocable.
  return (
    <div className={cls} onClick={onOpen} tabIndex={onOpen ? 0 : undefined}
      onKeyDown={(e) => { if (onOpen && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen(); } }}>
      <Photo code={p.feb_code} name={p.name} />
      <div className="prow__body">
        <div className="prow__name">{prettyName(p.name)}</div>
        <div className="prow__team">{prettyTeam(p.team) || "—"}</div>
        <div className="prow__meta">
          {!hidePrice && <span className="prow__price num">{p.price} M€</span>}
          {p.live && <span className="prow__avg">media {fp(p).toFixed(1)}</span>}
          {meta}
          {!!p.bids && <span className="prow__bids"><IconGavel size={11} strokeWidth={2.2} />{p.bids}</span>}
          {p.departed && <span className="prow__gone">No puntúa</span>}
        </div>
      </div>
      <div className="prow__side">
        {hero ?? (p.live
          // Jugándose la jornada, el número grande es lo que lleva HOY: la media de la
          // temporada no se mira mientras la bola está en el aire.
          ? (p.live_fp == null
              ? <div className="pfbox pfbox--wait"><b>—</b><span>juega</span></div>
              : <PfBox value={p.live_fp} label="hoy" muted={p.departed} />)
          : <PfBox value={pfValue ?? fp(p)} muted={p.departed} />)}
        {right}
      </div>
    </div>
  );
}

/** Cláusula del jugador, en la línea de datos de la fila. */
export function ClauseMeta({ p }: { p: RowPlayer }) {
  if (p.clause == null) return null;
  return (
    <span className="prow__clause"
      title={p.clause_locked
        ? "Cláusula de rescisión, bloqueada por ser un fichaje reciente"
        : "Cláusula de rescisión: lo que otro mánager tiene que pagarte por él"}>
      {p.clause_locked ? <IconLock size={11} strokeWidth={2.4} /> : <IconBolt size={11} strokeWidth={2.4} />}
      {p.clause}
    </span>
  );
}

/** Su equipo no juega esta jornada: sumará cero se ponga como se ponga. */
export function RestMeta({ p }: { p: RowPlayer }) {
  if (!p.rests || p.departed) return null;
  return <span className="prow__rest"><IconCalendar size={11} strokeWidth={2.4} />descansa</span>;
}

/** Variación de precio desde que lo fichaste. */
export function Delta({ v }: { v?: number }) {
  if (v == null || Math.abs(v) < 0.05) return null;
  return <Trend v={v} suffix=" M€" />;
}

/** Los símbolos de las filas, explicados una vez. Meter la palabra dentro de cada fila
 *  partía la línea en dos y hacía crecer todas las tarjetas: sale más caro de lo que vale. */
export function Leyenda() {
  return (
    <div className="leyenda">
      <span><IconBolt size={11} strokeWidth={2.4} />cláusula de rescisión</span>
      <span><IconLock size={11} strokeWidth={2.4} />cláusula bloqueada</span>
      <span><IconTrendUp size={11} strokeWidth={2.4} />cambio de valor</span>
    </div>
  );
}

export function FeedRow({ e }: { e: { id: number; kind: string; text: string; at: string } }) {
  const Icon = FEED_ICON[e.kind] ?? IconInfo;
  return (
    <div className={`tlrow tlrow--${e.kind}`}>
      <span className="tlrow__ico"><Icon size={16} strokeWidth={2} /></span>
      <div className="tlrow__txt">{stripEmoji(e.text)}</div>
      <div className="tlrow__at">{relTime(e.at)}</div>
    </div>
  );
}
