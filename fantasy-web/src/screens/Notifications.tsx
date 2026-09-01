/* ============================================================================
   Campana: lo que te ha pasado a ti (no lo que ha pasado en la liga, que eso es
   el feed). Se refresca sola y se marca como leído al abrirla.
   ========================================================================== */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import {
  IconBell, IconBolt, IconCalendar, IconGavel, IconInfo, IconMarket, IconPen, IconUserPlus,
  type IconProps,
} from "../icons";
import { Empty, Sheet, SheetClose, relTime } from "../ui";
import type { ReactNode } from "react";

const ICON: Record<string, (p: IconProps) => ReactNode> = {
  market: IconMarket,
  signing: IconPen,
  outbid: IconGavel,
  clause: IconBolt,
  jornada: IconCalendar,
  join: IconUserPlus,
  info: IconInfo,
};

export default function NotificationBell({ label }: { label?: string }) {
  const [data, setData] = useState<{ items: any[]; unread: number } | null>(null);
  const [open, setOpen] = useState(false);

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
        <Sheet onClose={() => setOpen(false)} title="Notificaciones">
          <div className="sheet__head" style={{ marginBottom: 12 }}>
            <div className="sheet__body">
              <h2>Notificaciones</h2>
              <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
                {items.length === 0 ? "Nada por ahora" : "Lo que te ha pasado en tus ligas"}
              </div>
            </div>
            <SheetClose onClose={() => setOpen(false)} />
          </div>

          {items.length === 0
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
            })}
        </Sheet>
      )}
    </>
  );
}
