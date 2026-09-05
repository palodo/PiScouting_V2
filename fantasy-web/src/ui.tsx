/* ============================================================================
   Primitivas de interfaz de PiFantasy: marca, pista, fotos, hojas inferiores,
   estados vacíos y utilidades de formato. Todo el color sale de index.css.
   ========================================================================== */
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { photo } from "./api";
import { IconClose, IconTrendDown, IconTrendUp, IconFlat } from "./icons";

/* ------------------------------------------------------------------- marca */
/** Balón monoline: la marca sin el aspecto de emoji del balón anterior. */
export function Ball({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <circle cx="20" cy="20" r="18" fill="var(--accent)" />
      <g stroke="var(--accent-ink)" strokeWidth="2" fill="none" strokeLinecap="round">
        <path d="M20 2v36M2 20h36" />
        <path d="M20 2Q-1.6 20 20 38" />
        <path d="M20 2Q41.6 20 20 38" />
      </g>
    </svg>
  );
}

export function Brand({ size = 34, name = true }: { size?: number; name?: boolean }) {
  return (
    <div className="brand">
      <Ball size={size} />
      {name && <span className="brand__name" style={{ fontSize: size * 0.62 }}>Pi<em>Fantasy</em></span>}
    </div>
  );
}

/* -------------------------------------------------------------------- pista */
/** Media pista sobria para colocar la formación. Los colores vienen de tokens. */
export function HalfCourt() {
  const W = 400, H = 300, cx = W / 2, hoop = 40, keyW = 112, keyH = 122;
  const kx = cx - keyW / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="pfcourt" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--court-bg)" />
          <stop offset="1" stopColor="var(--court-bg-2)" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width={W} height={H} rx="18" fill="url(#pfcourt)" />
      <g fill="none" stroke="var(--court-line)" strokeWidth="1.4" strokeLinecap="round">
        {/* zona */}
        <rect x={kx} y={hoop} width={keyW} height={keyH} />
        <path d={`M ${kx} ${hoop + keyH} A ${keyW / 2} ${keyW / 2} 0 0 0 ${kx + keyW} ${hoop + keyH}`} />
        <path d={`M ${kx} ${hoop + keyH} A ${keyW / 2} ${keyW / 2} 0 0 1 ${kx + keyW} ${hoop + keyH}`}
          strokeDasharray="5 6" opacity="0.55" />
        {/* canasta */}
        <line x1={cx - 26} y1={hoop} x2={cx + 26} y2={hoop} strokeWidth="2.6" />
        <circle cx={cx} cy={hoop + 10} r="7.5" strokeWidth="1.8" />
        {/* triple */}
        <path d={`M 34 ${hoop} L 34 ${hoop + 46} A 152 152 0 0 0 ${W - 34} ${hoop + 46} L ${W - 34} ${hoop}`} />
        {/* medio campo */}
        <line x1="0" y1={H - 26} x2={W} y2={H - 26} opacity="0.5" />
        <path d={`M ${cx - 40} ${H - 26} A 40 40 0 0 1 ${cx + 40} ${H - 26}`} opacity="0.7" />
      </g>
      <rect x="0.7" y="0.7" width={W - 1.4} height={H - 1.4} rx="18" fill="none"
        stroke="var(--border)" strokeWidth="1.4" />
    </svg>
  );
}

/* -------------------------------------------------------------------- fotos */
/* La FEB manda los nombres en mayúsculas ("A. ABELLO GIRVÉS"); en caja de título
   se leen mucho mejor y la interfaz deja de parecer que grita. */
const PARTICLES = new Set(["de", "del", "la", "las", "los", "van", "von", "der", "den", "da",
  "do", "dos", "di", "mc", "mac", "st", "el", "al", "ben", "bin", "y", "i"]);

function words(name?: string | null) {
  const raw = (name ?? "").includes(",") ? (name ?? "").split(",")[0] : (name ?? "");
  return raw.trim().toLowerCase().split(/\s+/).filter(Boolean).map((w, i) => {
    if (w.endsWith(".") || w.length === 1) return w.toUpperCase();
    if (i > 0 && PARTICLES.has(w)) return w;
    return w.replace(/(^|[-'])(\p{L})/gu, (_, s, c) => s + c.toUpperCase());
  });
}

/** Nombre completo, en caja de título ("J. Peris Crespo"). Para la ficha. */
export function fullName(name?: string | null) {
  return words(name).join(" ");
}

/**
 * Nombre corto para listas: inicial y PRIMER apellido ("J. Peris"). Los dos apellidos
 * llenan la fila y no aportan nada cuando ya ves la foto y el equipo. Las partículas se
 * pegan al apellido que les toca, que si no salen cosas como "J. Van".
 */
export function prettyName(name?: string | null) {
  const w = words(name);
  const out: string[] = [];
  for (const x of w) {
    out.push(x);
    const inicial = x.endsWith(".") || x.length === 1;
    if (!inicial && !PARTICLES.has(x.toLowerCase())) break;
  }
  return out.join(" ");
}

/** Igual para los equipos, pero respetando siglas con punto ("C.B. GETAFE"). */
export function prettyTeam(team?: string | null) {
  return (team ?? "").trim().toLowerCase().split(/\s+/).filter(Boolean).map((w, i) => {
    if (w.includes(".")) return w.toUpperCase();
    if (i > 0 && PARTICLES.has(w)) return w;
    return w.replace(/(^|[-'])(\p{L})/gu, (_, s, c) => s + c.toUpperCase());
  }).join(" ");
}

export function initials(name?: string | null) {
  const n = (name ?? "").replace(/,/g, " ").trim().split(/\s+/).filter(Boolean);
  if (!n.length) return "—";
  return (n[0][0] + (n[1]?.[0] ?? "")).toUpperCase();
}

/** Foto del jugador con reserva de iniciales (la FEB no tiene foto de todos). */
export function Photo({ code, name, variant }: {
  code?: string | null; name?: string | null; variant?: "lg" | "sm" | "tok";
}) {
  const [bad, setBad] = useState(false);
  useEffect(() => setBad(false), [code]);
  return (
    <div className={"photo" + (variant ? ` photo--${variant}` : "")}>
      <span className="photo__ini">{initials(name)}</span>
      {code && !bad && <img src={photo(code)} alt="" loading="lazy" onError={() => setBad(true)} />}
    </div>
  );
}

/* --------------------------------------------------------------- tendencia */
export function Trend({ v, suffix }: { v: number; suffix?: string }) {
  if (v > 0.4) return <span className="trend trend--up"><IconTrendUp size={13} strokeWidth={2.2} />{v.toFixed(1)}{suffix}</span>;
  if (v < -0.4) return <span className="trend trend--down"><IconTrendDown size={13} strokeWidth={2.2} />{Math.abs(v).toFixed(1)}{suffix}</span>;
  return <span className="trend trend--flat"><IconFlat size={13} strokeWidth={2.2} /></span>;
}

/* ------------------------------------------------------------------- hojas */
export function Sheet({ children, onClose, title }: {
  children: ReactNode; onClose: () => void; title?: string;
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    // el que scrollea es el contenido del shell, no el documento (ver index.css)
    document.documentElement.classList.add("sheet-open");
    return () => {
      document.removeEventListener("keydown", esc);
      document.documentElement.classList.remove("sheet-open");
    };
  }, [onClose]);
  // Portal a <body> a propósito: la barra superior lleva backdrop-filter, y eso crea un
  // bloque contenedor que atrapa a los hijos `position: fixed`. Sin esto, una hoja abierta
  // desde la campana se dibujaba DENTRO de la cabecera (58 px de alto) y no se veía.
  return createPortal(
    <div className="overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet__grab" />
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function SheetClose({ onClose }: { onClose: () => void }) {
  return <button className="iconbtn" onClick={onClose} aria-label="Cerrar"><IconClose size={20} /></button>;
}

/* ------------------------------------------------------------- estructurales */
export function Section({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="sect">
      <span>{children}</span>
      <span className="sect__line" />
      {right && <span className="sect__n">{right}</span>}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { v: T; label: string }[];
}) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button key={o.v} role="tab" aria-selected={value === o.v}
          className={"seg__btn" + (value === o.v ? " is-on" : "")}
          onClick={() => onChange(o.v)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon && <span className="empty__ico">{icon}</span>}
      <b>{title}</b>
      {children && <span>{children}</span>}
    </div>
  );
}

export function Loading({ label = "Cargando" }: { label?: string }) {
  return <div className="loading"><span className="spinner" />{label}…</div>;
}

export function SkeletonList({ n = 4 }: { n?: number }) {
  return <>{Array.from({ length: n }, (_, i) => <div key={i} className="skel skel--row" />)}</>;
}

/* ------------------------------------------------------------------- tiempo */
/** Reloj compartido: un solo intervalo por componente que lo use. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Cuenta atrás hasta una fecha ISO (formato hh:mm:ss, con días si toca). */
export function useCountdown(iso: string | null | undefined) {
  const now = useNow();
  if (!iso) return null;
  const left = new Date(iso).getTime() - now;
  return fmtLeft(left);
}

export function fmtLeft(ms: number) {
  if (ms <= 0) return "00:00:00";
  const p = (n: number) => String(n).padStart(2, "0");
  const d = Math.floor(ms / 86400000);
  const h = Math.floor(ms / 3600000) % 24;
  const m = Math.floor(ms / 60000) % 60;
  const s = Math.floor(ms / 1000) % 60;
  return d > 0 ? `${d}d ${p(h)}:${p(m)}` : `${p(h)}:${p(m)}:${p(s)}`;
}

const DAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

export function fmtWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  const hoy = new Date();
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === hoy.toDateString()) return `hoy a las ${hm}`;
  // más de una semana vista: "el viernes" ya no dice cuál, así que se pone la fecha
  if (d.getTime() - hoy.getTime() > 6 * 86400000) {
    return `el ${d.toLocaleDateString("es-ES", { day: "numeric", month: "short" })} a las ${hm}`;
  }
  return `${DAYS[d.getDay()]} a las ${hm}`;
}

export function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60000);
  if (m < 1) return "ahora mismo";
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.round(h / 24);
  if (d < 7) return `hace ${d} ${d === 1 ? "día" : "días"}`;
  return new Date(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
}

/** El backend mete emojis en el texto del feed; aquí los quitamos y ponemos icono. */
const EMOJI = new RegExp("[\\u{1F000}-\\u{1FAFF}\\u{2190}-\\u{2BFF}\\u{2600}-\\u{27BF}\\u{FE00}-\\u{FE0F}]", "gu");
export const stripEmoji = (t: string) => (t ?? "").replace(EMOJI, "").replace(/\s{2,}/g, " ").trim();

export const M = (v: number | null | undefined) => `${v ?? 0} M€`;

/* -------------------------------------------------------------------- tema */
export type ThemeMode = "auto" | "dark" | "light";
const THEME_KEY = "pf_theme";

export function readTheme(): ThemeMode {
  const v = localStorage.getItem(THEME_KEY);
  return v === "dark" || v === "light" ? v : "auto";
}

export function applyTheme(mode: ThemeMode) {
  const el = document.documentElement;
  if (mode === "auto") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", mode);
  localStorage.setItem(THEME_KEY, mode);
  const dark = mode === "dark"
    || (mode === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#080c14" : "#f3f5f9");
}

export function useThemeMode(): [ThemeMode, (m: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(readTheme);
  useEffect(() => { applyTheme(mode); }, [mode]);
  return [mode, setMode];
}
