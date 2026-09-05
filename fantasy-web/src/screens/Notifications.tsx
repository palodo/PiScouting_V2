/* ============================================================================
   Campana: las novedades. Dos solapas, porque son dos cosas distintas: lo que te
   ha pasado a ti (avisos, se marcan leídos al abrir) y lo que se mueve en la liga
   (el feed, que antes vivía en una pestaña propia). Se refresca sola.
   ========================================================================== */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import {
  IconActivity, IconBell, IconBolt, IconCalendar, IconCoin, IconGavel, IconInfo, IconMarket,
  IconPen, IconUserPlus,
  type IconProps,
} from "../icons";
import { Empty, Segmented, Sheet, SheetClose, relTime } from "../ui";
import { FeedRow } from "../parts";
import type { ReactNode } from "react";

const ICON: Record<string, (p: IconProps) => ReactNode> = {
  market: IconMarket,
  signing: IconPen,
  outbid: IconGavel,
  clause: IconBolt,
  jornada: IconCalendar,
  join: IconUserPlus,
  bet: IconCoin,
  info: IconInfo,
};

export default function NotificationBell({ label, feed }: {
  label?: string;
  /** Actividad de la liga. Solo llega desde dentro de una liga; en "mis ligas" no hay. */
  feed?: any[];
}) {
  const [data, setData] = useState<{ items: any[]; unread: number } | null>(null);
  const [open, setOpen] = useState(false);
  const [vista, setVista] = useState<"tuyo" | "liga">("tuyo");

  const refresh = useCallback(() => {
    api.notifications().then(setData).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000);
    // al volver a la app (típico en el móvil) se mira si hay algo nuevo
    const onShow = () => { if (!document.hidden) refresh(); };
    document.addEventListener("visibilitychange", onShow);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", onShow); };
  }, [refresh]);

  function openSheet() {
    setOpen(true);
    if (data?.unread) {
      api.readNotifications()
        .then(() => setData((d) => (d ? { ...d, unread: 0 } : d)))
        .catch(() => {});
    }
  }

  const unread = data?.unread ?? 0;
  const items = data?.items ?? [];

  return (
    <>
      <button className="iconbtn bell" onClick={openSheet} aria-label={label ?? "Notificaciones"}>
        <IconBell size={20} />
        {unread > 0 && <span className="bell__badge num">{unread > 9 ? "9+" : unread}</span>}
      </button>

      {open && (
        <Sheet onClose={() => setOpen(false)} title="Novedades">
          <div className="sheet__head" style={{ marginBottom: 12 }}>
            <div className="sheet__body">
              <h2>Novedades</h2>
              <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
                {vista === "liga" ? "Todo lo que se mueve en la liga"
                  : items.length === 0 ? "Nada por ahora" : "Lo que te ha pasado a ti"}
              </div>
            </div>
            <SheetClose onClose={() => setOpen(false)} />
          </div>

          {feed && (
            <div style={{ marginBottom: 12 }}>
              <Segmented value={vista} onChange={setVista} options={[
                { v: "tuyo", label: unread ? `Para ti · ${unread}` : "Para ti" },
                { v: "liga", label: "La liga" },
              ]} />
            </div>
          )}

          {vista === "liga" && (
            (feed ?? []).length === 0
              ? <Empty icon={<IconActivity size={22} />} title="Sin movimientos todavía">
                  Aquí aparecen los fichajes, los clausulazos y las jornadas puntuadas.
                </Empty>
              : <div className="tl">{feed!.map((e: any) => <FeedRow key={e.id} e={e} />)}</div>
          )}

          {vista === "tuyo" && (items.length === 0
            ? <Empty icon={<IconBell size={22} />} title="Sin novedades">
                Aquí te avisaremos de los clausulazos que sufras, de las pujas que ganes
                o pierdas y de lo que hagas cada jornada.
              </Empty>
            : items.map((n) => {
              const Icon = ICON[n.kind] ?? IconInfo;
              return (
                <div key={n.id} className={"notif notif--" + n.kind + (n.read ? "" : " is-new")}>
                  <span className="notif__ico"><Icon size={17} strokeWidth={2} /></span>
                  <div className="notif__body">
                    <div className="notif__title">{n.title}</div>
                    {n.body && <div className="notif__text">{n.body}</div>}
                    <div className="notif__at">{n.league} · {relTime(n.at)}</div>
                  </div>
                </div>
              );
            }))}
        </Sheet>
      )}
    </>
  );
}
