/* ============================================================================
   Iconos de PiFantasy — SVG de trazo, 24×24, `currentColor`.
   Todos comparten rejilla y grosor para que la interfaz se lea como un sistema
   (antes había emojis: no escalan, cambian de forma según el móvil y no heredan
   el color del texto).
   ========================================================================== */
import type { ReactNode, SVGProps } from "react";

export type IconProps = { size?: number; strokeWidth?: number } & Omit<SVGProps<SVGSVGElement>, "size">;

/** Fábrica de iconos de trazo. */
function stroke(d: ReactNode) {
  return function Icon({ size = 20, strokeWidth = 1.7, ...rest }: IconProps) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true" focusable="false" {...rest}>{d}</svg>
    );
  };
}
/** Fábrica de iconos macizos (para estados activos: estrella marcada, play…). */
function solid(d: ReactNode) {
  return function Icon({ size = 20, ...rest }: IconProps) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor"
        aria-hidden="true" focusable="false" {...rest}>{d}</svg>
    );
  };
}

/* ---------------------------------------------------------------- navegación */
export const IconSquad = stroke(<>
  <circle cx="9.2" cy="7.8" r="3.5" />
  <path d="M3.4 19.4v-.8a4.6 4.6 0 0 1 4.6-4.6h2.4a4.6 4.6 0 0 1 4.6 4.6v.8" />
  <path d="M16.6 5.1a3.2 3.2 0 0 1 0 6.1" />
  <path d="M17.9 14.4a4 4 0 0 1 2.7 3.8v1.2" />
</>);
export const IconMarket = stroke(<>
  <path d="M5.3 8h13.4l-1.1 11a1.9 1.9 0 0 1-1.9 1.7H8.3A1.9 1.9 0 0 1 6.4 19L5.3 8Z" />
  <path d="M9 8V6.4a3 3 0 0 1 6 0V8" />
</>);
export const IconTrophy = stroke(<>
  <path d="M7.8 3.6h8.4v5.1a4.2 4.2 0 0 1-8.4 0V3.6Z" />
  <path d="M7.8 5.5H5.4A1.4 1.4 0 0 0 4 6.9a3.6 3.6 0 0 0 3.6 3.6h.4" />
  <path d="M16.2 5.5h2.4A1.4 1.4 0 0 1 20 6.9a3.6 3.6 0 0 1-3.6 3.6H16" />
  <path d="M12 12.9v3.3" />
  <path d="M8.6 20.4a3.4 3.4 0 0 1 6.8 0Z" />
</>);
export const IconActivity = stroke(<path d="M3 12.2h3.7L9.1 6l3.7 12 2.5-5.8H21" />);

/* --------------------------------------------------------------- indicadores */
export const IconStar = stroke(
  <path d="m12 3.7 2.6 5.2 5.7.8-4.1 4 1 5.7-5.2-2.7-5.2 2.7 1-5.7-4.1-4 5.7-.8L12 3.7Z" />);
export const IconStarOn = solid(
  <path d="m12 3.2 2.8 5.6 6.2.9a.6.6 0 0 1 .3 1l-4.5 4.4 1.1 6.2a.6.6 0 0 1-.9.6L12 18l-5.5 2.9a.6.6 0 0 1-.9-.6l1-6.2-4.4-4.4a.6.6 0 0 1 .3-1l6.2-.9L11.5 3a.6.6 0 0 1 1 0Z" />);
export const IconLock = stroke(<>
  <rect x="4.7" y="10" width="14.6" height="10.3" rx="2.6" />
  <path d="M8.2 10V7.4a3.8 3.8 0 0 1 7.6 0V10" />
</>);
export const IconBolt = stroke(
  <path d="M13.4 2.7 4.9 13.2a.7.7 0 0 0 .5 1.1h5.1l-.9 7.1 8.5-10.5a.7.7 0 0 0-.5-1.1h-5.1l.8-7.1Z" />);
export const IconBoltOn = solid(
  <path d="M13.9 2.1a.6.6 0 0 1 1 .7l-1 6.4h4.3a.9.9 0 0 1 .7 1.5l-8.8 11a.6.6 0 0 1-1-.6l1-6.5H5.8a.9.9 0 0 1-.7-1.5l8.8-11Z" />);
export const IconCoin = stroke(<>
  <circle cx="12" cy="12" r="8.4" />
  <path d="M15.4 9.4a3.9 3.9 0 0 0-6.2 1.1" />
  <path d="M15.4 14.6a3.9 3.9 0 0 1-6.2-1.1" />
  <path d="M7.7 11.1h5.1M7.7 13.3h5.1" />
</>);
export const IconClock = stroke(<>
  <circle cx="12" cy="12" r="8.4" />
  <path d="M12 7.3V12l3.2 1.9" />
</>);
export const IconGavel = stroke(<>
  <path d="M14.8 3.3a1 1 0 0 1 1.4 0l4.1 4.1a1 1 0 0 1 0 1.4l-1.7 1.7a1 1 0 0 1-1.4 0l-4.1-4.1a1 1 0 0 1 0-1.4l1.7-1.7Z" />
  <path d="m14.2 8.7-7.9 7.9a2.2 2.2 0 1 0 3.1 3.1l7.9-7.9" />
</>);
export const IconTrendUp = stroke(<>
  <path d="m3.8 16.6 5.9-6.4 3.4 3.4 6.6-6.8" />
  <path d="M14.6 6.8h5.4v5.4" />
</>);
export const IconTrendDown = stroke(<>
  <path d="m3.8 7.4 5.9 6.4 3.4-3.4 6.6 6.8" />
  <path d="M14.6 17.2h5.4v-5.4" />
</>);
export const IconFlat = stroke(<path d="M4.5 12h15" />);
export const IconAlert = stroke(<>
  <path d="M12 4.4 3.2 19.6h17.6L12 4.4Z" />
  <path d="M12 10.1v3.9" />
  <circle cx="12" cy="16.9" r=".95" fill="currentColor" stroke="none" />
</>);
export const IconInfo = stroke(<>
  <circle cx="12" cy="12" r="8.4" />
  <path d="M12 11.2v4.9" />
  <circle cx="12" cy="8.1" r=".95" fill="currentColor" stroke="none" />
</>);

/* -------------------------------------------------------------------- acción */
export const IconChevronLeft = stroke(<path d="m14.4 6.4-5.6 5.6 5.6 5.6" />);
export const IconChevronRight = stroke(<path d="m9.6 6.4 5.6 5.6-5.6 5.6" />);
export const IconArrowLeft = stroke(<path d="M19.2 12H4.8m6.4-6.4L4.8 12l6.4 6.4" />);
export const IconCopy = stroke(<>
  <rect x="8.7" y="8.7" width="11.7" height="11.7" rx="2.6" />
  <path d="M15.3 6.5V6a2.4 2.4 0 0 0-2.4-2.4H6A2.4 2.4 0 0 0 3.6 6v6.9a2.4 2.4 0 0 0 2.4 2.4h.5" />
</>);
export const IconCheck = stroke(<path d="m5.2 12.6 4.6 4.6L18.8 6.8" />);
export const IconClose = stroke(<path d="M6.3 6.3 17.7 17.7M17.7 6.3 6.3 17.7" />);
export const IconPlus = stroke(<path d="M12 5.2v13.6M5.2 12h13.6" />);
export const IconMinus = stroke(<path d="M5.2 12h13.6" />);
export const IconPlay = solid(<path d="M7.6 4.7a.7.7 0 0 1 1.1-.6l10.1 6.9a.8.8 0 0 1 0 1.3L8.7 19.2a.7.7 0 0 1-1.1-.6V4.7Z" />);
export const IconLogout = stroke(<>
  <path d="M14.3 6.6v-.8a2.3 2.3 0 0 0-2.3-2.3H6.1a2.3 2.3 0 0 0-2.3 2.3v12.4a2.3 2.3 0 0 0 2.3 2.3H12a2.3 2.3 0 0 0 2.3-2.3v-.8" />
  <path d="M20.2 12H9.5m7.1-3.6 3.6 3.6-3.6 3.6" />
</>);
export const IconBell = stroke(<>
  <path d="M18.2 15.6V10.6a6.2 6.2 0 1 0-12.4 0v5l-1.5 2.6h15.4l-1.5-2.6Z" />
  <path d="M9.7 20.5a2.5 2.5 0 0 0 4.6 0" />
</>);
export const IconBellOff = stroke(<>
  <path d="M18.2 15.6V10.6a6.2 6.2 0 0 0-9-5.5" />
  <path d="M5.8 9.4v6.2l-1.5 2.6h12.3" />
  <path d="M9.7 20.5a2.5 2.5 0 0 0 4.6 0M3.4 3.4l17.2 17.2" />
</>);
export const IconShare = stroke(<>
  <path d="M12 15.4V3.4m0 0L8.6 6.8M12 3.4l3.4 3.4" />
  <path d="M7.2 10.4h-1a2 2 0 0 0-2 2v6.2a2 2 0 0 0 2 2h11.6a2 2 0 0 0 2-2v-6.2a2 2 0 0 0-2-2h-1" />
</>);
export const IconWhatsApp = stroke(<>
  <path d="M3.6 20.4l1.2-4.3a8 8 0 1 1 3.1 3.1l-4.3 1.2Z" />
  <path d="M9 8.6c.2 1.9 1.4 4 3.2 5 .9.5 1.6.7 2.1.4.3-.2.5-.5.7-.9.1-.3 0-.5-.2-.7l-1.3-.8c-.2-.1-.5-.1-.7.1l-.4.5c-1-.5-1.8-1.3-2.3-2.3l.5-.4c.2-.2.2-.5.1-.7l-.8-1.3c-.2-.2-.4-.3-.7-.2-.4.2-.7.4-.9.7-.2.3-.3.6-.3 1Z" />
</>);
export const IconSearch = stroke(<>
  <circle cx="11" cy="11" r="6.6" />
  <path d="m16 16 4.4 4.4" />
</>);
export const IconSliders = stroke(<>
  <path d="M4 7.5h9.2M18.4 7.5H20M4 16.5h3.6M12.8 16.5H20" />
  <circle cx="15.8" cy="7.5" r="2.5" />
  <circle cx="10.2" cy="16.5" r="2.5" />
</>);
export const IconSun = stroke(<>
  <circle cx="12" cy="12" r="4.1" />
  <path d="M12 2.8v2.1M12 19.1v2.1M2.8 12h2.1M19.1 12h2.1M5.5 5.5l1.5 1.5M17 17l1.5 1.5M18.5 5.5 17 7M7 17l-1.5 1.5" />
</>);
export const IconMoon = stroke(
  <path d="M20.3 14.6A8.5 8.5 0 0 1 9.4 3.7a8.6 8.6 0 1 0 10.9 10.9Z" />);

/* ------------------------------------------------------- eventos del feed */
export const IconPen = stroke(<>
  <path d="M4 20.3h16" />
  <path d="M14.7 4.7a1.9 1.9 0 0 1 2.6 2.6l-8.2 8.2-3.4.8.8-3.4 8.2-8.2Z" />
</>);
export const IconTag = stroke(<>
  <path d="M11.6 3.6H5.5a1.9 1.9 0 0 0-1.9 1.9v6.1c0 .5.2 1 .6 1.4l7 7a1.9 1.9 0 0 0 2.7 0l6.1-6.1a1.9 1.9 0 0 0 0-2.7l-7-7c-.4-.4-.9-.6-1.4-.6Z" />
  <circle cx="8.2" cy="8.2" r="1.3" />
</>);
export const IconUserPlus = stroke(<>
  <circle cx="9.4" cy="7.8" r="3.5" />
  <path d="M3.4 19.4v-.8a4.6 4.6 0 0 1 4.6-4.6h2.8a4.6 4.6 0 0 1 4.6 4.6v.8" />
  <path d="M18.4 8.4v5.2M15.8 11h5.2" />
</>);
export const IconCalendar = stroke(<>
  <rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.6" />
  <path d="M3.6 10h16.8M8.2 3.4v3.4M15.8 3.4v3.4" />
</>);
export const IconTransfer = stroke(<>
  <path d="M4 8.4h13.4m-3.5-3.5 3.5 3.5-3.5 3.5" />
  <path d="M20 15.6H6.6m3.5-3.5-3.5 3.5 3.5 3.5" />
</>);

/** Icono para cada `kind` del feed que devuelve el backend. */
export const FEED_ICON: Record<string, (p: IconProps) => ReactNode> = {
  market: IconMarket,
  signing: IconPen,
  clause: IconBolt,
  sale: IconTag,
  jornada: IconCalendar,
  join: IconUserPlus,
  info: IconInfo,
};
