import { useEffect, useMemo, useRef, useState } from "react";
import type { Shot } from "../api";

// Media pista vertical. Sistema de coordenadas de entrada:
//   hx: 0 = medio campo (arriba) .. 100 = línea de fondo (abajo)
//   hy: 0..100 a lo ancho
// Dibujamos una media pista FIBA aproximada (15m ancho x 14m largo) a 30px/m.
const M = 30;
const COURT_W = 15 * M; // 450
const COURT_H = 14 * M; // 420
const PAD = 10;
const W = COURT_W + PAD * 2;
const H = COURT_H + PAD * 2;

function courtX(hy: number) {
  return PAD + (hy / 100) * COURT_W;
}
function courtY(hx: number) {
  return PAD + (hx / 100) * COURT_H;
}

function CourtLines() {
  const hoopY = PAD + COURT_H - 1.575 * M;
  const hoopX = PAD + COURT_W / 2;
  const keyW = 4.9 * M;
  const keyH = 5.8 * M;
  const keyX = hoopX - keyW / 2;
  const keyY = PAD + COURT_H - keyH;
  const stroke = "var(--court-line)";
  return (
    <g fill="none" stroke={stroke} strokeWidth={1.6}>
      <rect x={PAD} y={PAD} width={COURT_W} height={COURT_H} rx={2} />
      {/* zona */}
      <rect x={keyX} y={keyY} width={keyW} height={keyH} />
      {/* semicírculo tiros libres */}
      <path d={`M ${keyX} ${keyY} A ${keyW / 2} ${keyW / 2} 0 0 0 ${keyX + keyW} ${keyY}`} />
      {/* aro y tablero */}
      <line x1={hoopX - 0.9 * M} y1={PAD + COURT_H - 1.2 * M} x2={hoopX + 0.9 * M} y2={PAD + COURT_H - 1.2 * M} strokeWidth={2.2} />
      <circle cx={hoopX} cy={hoopY} r={0.225 * M} strokeWidth={2} />
      {/* línea de 3: arco 6.75m + tramos rectos en las esquinas (0.9m del lateral) */}
      <path
        d={`M ${PAD + 0.9 * M} ${PAD + COURT_H}
            L ${PAD + 0.9 * M} ${PAD + COURT_H - 2.99 * M}
            A ${6.75 * M} ${6.75 * M} 0 0 0 ${PAD + COURT_W - 0.9 * M} ${PAD + COURT_H - 2.99 * M}
            L ${PAD + COURT_W - 0.9 * M} ${PAD + COURT_H}`}
      />
      {/* semicírculo de medio campo (arriba) */}
      <path d={`M ${hoopX - 1.8 * M} ${PAD} A ${1.8 * M} ${1.8 * M} 0 0 0 ${hoopX + 1.8 * M} ${PAD}`} />
    </g>
  );
}

interface Props {
  shots: Shot[];
  animate?: boolean;
  height?: number;
}

export default function ShotChart({ shots, animate = false, height = 460 }: Props) {
  const ordered = useMemo(
    () => [...shots].sort((a, b) => (a.t ?? 0) - (b.t ?? 0)),
    [shots]
  );
  const maxT = ordered.length ? ordered[ordered.length - 1].t ?? 0 : 0;
  const [cursor, setCursor] = useState(maxT || 1);
  const [playing, setPlaying] = useState(false);
  const raf = useRef<number>();

  useEffect(() => {
    setCursor(maxT || 1);
  }, [maxT]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setCursor((c) => {
        const next = c + dt * 90; // 90 s de partido por segundo real
        if (next >= maxT) {
          setPlaying(false);
          return maxT;
        }
        return next;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [playing, maxT]);

  const visible = animate ? ordered.filter((s) => (s.t ?? 0) <= cursor) : ordered;
  const made = visible.filter((s) => s.made).length;

  function fmt(t: number) {
    const q = t <= 2400 ? Math.floor(t / 600) + 1 : 5 + Math.floor((t - 2400) / 300);
    return `Q${Math.min(q, 10)}`;
  }

  return (
    <div className="shotchart">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height, background: "var(--court-bg)", borderRadius: 12 }}>
        <CourtLines />
        {visible.map((s, i) => (
          <circle
            key={i}
            cx={courtX(s.hy)}
            cy={courtY(s.hx)}
            r={5.5}
            fill={s.made ? "var(--made)" : "none"}
            stroke={s.made ? "var(--made)" : "var(--miss)"}
            strokeWidth={2}
            opacity={0.9}
          >
            {s.made ? null : <title>Fallado</title>}
          </circle>
        ))}
      </svg>
      <div className="shot-legend">
        <span><i className="dot made" /> Anotado</span>
        <span><i className="dot miss" /> Fallado</span>
        <span className="muted">
          {visible.length} tiros · {made} anotados ·{" "}
          {visible.length ? Math.round((made / visible.length) * 100) : 0}%
        </span>
      </div>
      {animate && maxT > 0 && (
        <div className="anim-controls">
          <button onClick={() => { if (cursor >= maxT) setCursor(0); setPlaying((p) => !p); }}>
            {playing ? "❚❚ Pausa" : "▶ Reproducir"}
          </button>
          <input
            type="range"
            min={0}
            max={maxT}
            value={cursor}
            onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }}
          />
          <span className="muted">{fmt(cursor)}</span>
        </div>
      )}
    </div>
  );
}
