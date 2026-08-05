/* ============================================================================
   Piezas compartidas entre pantallas: la fila de jugador (mercado, plantilla y
   plantilla del rival) y la fila del feed.
   ========================================================================== */
import type { ReactNode } from "react";
import { FEED_ICON, IconBolt, IconGavel, IconInfo, IconLock } from "./icons";
import { Photo, Trend, prettyName, prettyTeam, relTime, stripEmoji } from "./ui";

export type RowPlayer = {
  player_id: number;
  name: string;
  feb_code?: string | null;
  team?: string | null;
  price: number;
  fp_avg?: number;
  fp_form?: number;
  val_avg?: number;
  form?: number;
  delta?: number;
  starter?: boolean;
  departed?: boolean;
  clause?: number | null;
  clause_locked?: boolean;
  clause_lock_mins?: number;
  bids?: number;
  my_bid?: number | null;
};

/** Puntos fantasy: el dato que de verdad suma. Si el backend es antiguo, VAL. */
export const fp = (p: { fp_avg?: number; val_avg?: number }) => p.fp_avg ?? p.val_avg ?? 0;
export const fpForm = (p: { fp_form?: number; form?: number }) => p.fp_form ?? p.form ?? 0;

export function lockLabel(mins?: number) {
  if (!mins || mins <= 0) return "";
  const h = Math.floor(mins / 60);
  return h > 0 ? `${h} h` : `${mins} min`;
}

/** El número que decide la liga, en grande y aislado del resto. */
export function PfBox({ value, muted, label = "PF" }: { value: number; muted?: boolean; label?: string }) {
  return (
    <div className={"pfbox" + (muted ? " pfbox--muted" : "")}>
      <b className="num">{muted ? "0" : value.toFixed(1)}</b>
      <span>{label}</span>
    </div>
  );
}

/**
 * Fila de jugador. A la izquierda quién es y cuánto vale; a la derecha, aislados,
 * los puntos fantasy. Las medias de valoración y demás se han bajado a la ficha:
 * de un vistazo solo debe competir un número.
 */
export function PlayerRow({ p, onOpen, right, tone, meta, hero, pf: pfValue }: {
  p: RowPlayer;
  onOpen?: () => void;
  right?: ReactNode;
  tone?: "starter" | "bid" | "gone";
  meta?: ReactNode;
  /** Sustituye la caja de PF cuando la pantalla va de otra cosa (p. ej. cláusulas). */
  hero?: ReactNode;
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
          <span className="prow__price num">{p.price} M€</span>
          {meta}
          {!!p.bids && <span className="prow__bids"><IconGavel size={11} strokeWidth={2.2} />{p.bids}</span>}
          {p.departed && <span className="prow__gone">No puntúa</span>}
        </div>
      </div>
      <div className="prow__side">
        {hero ?? <PfBox value={pfValue ?? fp(p)} muted={p.departed} />}
        {right}
      </div>
    </div>
  );
}

/** Cláusula del jugador, en la línea de datos de la fila. */
export function ClauseMeta({ p }: { p: RowPlayer }) {
  if (p.clause == null) return null;
  return (
    <span className="prow__clause">
      {p.clause_locked ? <IconLock size={11} strokeWidth={2.4} /> : <IconBolt size={11} strokeWidth={2.4} />}
      {p.clause}
    </span>
  );
}

/** Variación de precio desde que lo fichaste. */
export function Delta({ v }: { v?: number }) {
  if (v == null || Math.abs(v) < 0.05) return null;
  return <Trend v={v} suffix=" M€" />;
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
