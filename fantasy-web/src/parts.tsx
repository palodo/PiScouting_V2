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

/**
 * Fila de jugador. `variant` cambia lo que se enseña a la derecha:
 *  · "market" → precio de salida y botón de puja
 *  · "squad"  → precio actual, variación desde la compra y acción
 *  · "plain"  → solo datos (plantilla de un rival)
 */
export function PlayerRow({ p, onOpen, right, tone }: {
  p: RowPlayer;
  onOpen?: () => void;
  right?: ReactNode;
  tone?: "starter" | "bid" | "gone";
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
        <div className="chiprow">
          {p.departed
            ? <span className="chip chip--neg">Ya no puntúa</span>
            : <span className="chip chip--accent"><b>{fp(p).toFixed(1)}</b> PF</span>}
          <span className="chip">VAL <b>{(p.val_avg ?? 0).toFixed(1)}</b></span>
          {p.clause != null && (
            <span className="chip chip--clause">
              {p.clause_locked ? <IconLock size={11} strokeWidth={2.2} /> : <IconBolt size={11} strokeWidth={2.2} />}
              <b>{p.clause}</b>
            </span>
          )}
          {!!p.bids && <span className="chip"><IconGavel size={11} strokeWidth={2.2} />{p.bids}</span>}
        </div>
      </div>
      <div className="prow__side">
        <div className="prow__price num">{p.price}<span> M€</span></div>
        {right}
      </div>
    </div>
  );
}

/** Variación de precio desde que lo fichaste. */
export function Delta({ v }: { v?: number }) {
  if (v == null) return null;
  return <Trend v={v} />;
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
