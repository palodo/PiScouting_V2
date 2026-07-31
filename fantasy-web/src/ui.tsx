import { useEffect, useState } from "react";

/** Balón de baloncesto (marca de la app). */
export function Ball({ size = 64, className }: { size?: number; className?: string }) {
  const r = size / 2 - 1, c = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={"ball " + (className ?? "")}>
      <defs>
        <radialGradient id="bg1" cx="0.35" cy="0.3" r="0.9">
          <stop offset="0" stopColor="#ff8a52" />
          <stop offset="0.6" stopColor="#ff6a2b" />
          <stop offset="1" stopColor="#d9410f" />
        </radialGradient>
      </defs>
      <circle cx={c} cy={c} r={r} fill="url(#bg1)" />
      <g fill="none" stroke="#8f2a08" strokeWidth={size * 0.055}>
        <line x1={c - r} y1={c} x2={c + r} y2={c} />
        <line x1={c} y1={c - r} x2={c} y2={c + r} />
        <path d={`M ${c - r * 0.98} ${c - r * 0.22} Q ${c} ${c + r * 0.3} ${c + r * 0.98} ${c - r * 0.22}`} />
        <path d={`M ${c - r * 0.98} ${c + r * 0.22} Q ${c} ${c - r * 0.3} ${c + r * 0.98} ${c + r * 0.22}`} />
      </g>
      <ellipse cx={c - r * 0.32} cy={c - r * 0.36} rx={r * 0.26} ry={r * 0.17} fill="#fff" opacity={0.28} />
    </svg>
  );
}

/** Media pista para colocar la formación. */
export function HalfCourt() {
  const W = 400, H = 300, cx = W / 2, hoopY = 38, keyW = 118, keyH = 124;
  const keyX = cx - keyW / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="ct" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1a2740" />
          <stop offset="1" stopColor="#101a2e" />
        </linearGradient>
      </defs>
      <rect x="5" y="5" width={W - 10} height={H - 10} rx="16" fill="url(#ct)" stroke="rgba(255,255,255,0.08)" strokeWidth="1.5" />
      <g fill="none" stroke="rgba(255,176,32,0.42)" strokeWidth="2">
        <rect x={keyX} y={hoopY} width={keyW} height={keyH} />
        <path d={`M ${keyX} ${hoopY + keyH} A ${keyW / 2} ${keyW / 2} 0 0 0 ${keyX + keyW} ${hoopY + keyH}`} />
        <line x1={cx - 28} y1={hoopY} x2={cx + 28} y2={hoopY} strokeWidth="3" />
        <circle cx={cx} cy={hoopY + 11} r="8.5" strokeWidth="2.4" />
        <path d={`M 38 ${hoopY} L 38 ${hoopY + 54} A 148 148 0 0 0 ${W - 38} ${hoopY + 54} L ${W - 38} ${hoopY}`} />
        <path d={`M ${cx - 44} ${H - 5} A 44 44 0 0 1 ${cx + 44} ${H - 5}`} />
      </g>
    </svg>
  );
}

/** Cuenta atrás viva hasta una fecha ISO. */
export function useCountdown(iso: string | null) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!iso) return null;
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return "00:00:00";
  const d = Math.floor(ms / 86400000);
  const h = Math.floor(ms / 3600000) % 24;
  const m = Math.floor(ms / 60000) % 60;
  const s = Math.floor(ms / 1000) % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return d > 0 ? `${d}d ${p(h)}:${p(m)}:${p(s)}` : `${p(h)}:${p(m)}:${p(s)}`;
}

export function Trend({ v }: { v: number }) {
  if (v > 0.4) return <span className="trend up">▲ {v.toFixed(1)}</span>;
  if (v < -0.4) return <span className="trend down">▼ {Math.abs(v).toFixed(1)}</span>;
  return <span className="trend muted">◆</span>;
}

export function fmtWhen(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  const days = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
  return `${days[d.getDay()]} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
