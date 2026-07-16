/* Ilustraciones isométricas dibujadas con SVG (sin dependencias ni imágenes externas).
   Proyección isométrica real 2:1 calculada a partir de coordenadas de pista en metros. */

const COS = 0.866, SIN = 0.5;

function project(x: number, y: number, z: number, s: number, ox: number, oy: number) {
  return [ox + (x - y) * COS * s, oy + (x + y) * SIN * s - z * s] as const;
}

/** Pista de baloncesto isométrica. Es la pieza central del rediseño. */
export function IsoCourt({ size = 460, className }: { size?: number; className?: string }) {
  const L = 28, W = 15, s = 8, ox = 250, oy = 116;
  const P = (x: number, y: number, z = 0) => project(x, y, z, s, ox, oy);
  const pt = (a: readonly [number, number]) => `${a[0].toFixed(1)},${a[1].toFixed(1)}`;
  const poly = (...c: (readonly [number, number])[]) => c.map(pt).join(" ");

  // esquinas del suelo
  const c00 = P(0, 0), c10 = P(L, 0), c11 = P(L, W), c01 = P(0, W);
  // canto del suelo (grosor) para dar volumen
  const t = 6;
  const e10 = [c10[0], c10[1] + t] as const;
  const e11 = [c11[0], c11[1] + t] as const;
  const e01 = [c01[0], c01[1] + t] as const;

  function hoop(baseX: number, dir: 1 | -1) {
    const y = W / 2;
    const poleBottom = P(baseX, y, 0);
    const poleTop = P(baseX, y, 3.3);
    const boardX = baseX + dir * 1.2;
    const bTopBack = P(boardX, y - 1.0, 3.5);
    const bTopFront = P(boardX, y + 1.0, 3.5);
    const bBotFront = P(boardX, y + 1.0, 2.6);
    const bBotBack = P(boardX, y - 1.0, 2.6);
    const rim = P(baseX + dir * 2.0, y, 3.05);
    return (
      <g>
        <line x1={poleBottom[0]} y1={poleBottom[1]} x2={poleTop[0]} y2={poleTop[1]} stroke="#8792a8" strokeWidth={3.4} strokeLinecap="round" />
        <polygon points={poly(bTopBack, bTopFront, bBotFront, bBotBack)} fill="#ffffff" stroke="#c4ccdb" strokeWidth={1} opacity={0.96} />
        <ellipse cx={rim[0]} cy={rim[1]} rx={5.6} ry={2.7} fill="none" stroke="#ff5a1f" strokeWidth={2.6} />
      </g>
    );
  }

  // líneas de pista
  const midTop = P(L / 2, 0), midBot = P(L / 2, W);
  const cc = P(L / 2, W / 2, 0);
  // llaves (zona) simplificadas
  const keyA = poly(P(0, W / 2 - 2.4), P(5.8, W / 2 - 2.4), P(5.8, W / 2 + 2.4), P(0, W / 2 + 2.4));
  const keyB = poly(P(L, W / 2 - 2.4), P(L - 5.8, W / 2 - 2.4), P(L - 5.8, W / 2 + 2.4), P(L, W / 2 + 2.4));

  return (
    <svg viewBox="0 0 500 350" width={size} height={size * 0.7} className={"iso " + (className ?? "")}
         xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="wood" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f6e3bd" />
          <stop offset="1" stopColor="#eccf95" />
        </linearGradient>
        <linearGradient id="woodEdge" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d8b878" />
          <stop offset="1" stopColor="#bd9856" />
        </linearGradient>
      </defs>
      {/* sombra */}
      <ellipse cx={cc[0]} cy={c11[1] + 26} rx={168} ry={40} fill="#28344a" opacity={0.08} />
      {/* cantos (volumen) */}
      <polygon points={poly(c01, c11, e11, e01)} fill="url(#woodEdge)" />
      <polygon points={poly(c11, c10, e10, e11)} fill="url(#woodEdge)" opacity={0.82} />
      {/* suelo */}
      <polygon points={poly(c00, c10, c11, c01)} fill="url(#wood)" stroke="#c79f5c" strokeWidth={1.4} />
      {/* líneas */}
      <g fill="none" stroke="#b5843a" strokeWidth={1.5} opacity={0.9}>
        <line x1={midTop[0]} y1={midTop[1]} x2={midBot[0]} y2={midBot[1]} />
        <ellipse cx={cc[0]} cy={cc[1]} rx={17} ry={8.5} />
        <polygon points={keyA} />
        <polygon points={keyB} />
      </g>
      {hoop(1.2, 1)}
      {hoop(L - 1.2, -1)}
      {/* balón flotando en el centro */}
      <IsoBall x={cc[0]} y={cc[1] - 58} r={20} className="floaty" />
    </svg>
  );
}

/** Balón de baloncesto estilizado (2D con sombreado, encaja en escenas isométricas). */
export function IsoBall({ x, y, r = 22, className }: { x: number; y: number; r?: number; className?: string }) {
  return (
    <g className={className}>
      <ellipse cx={x} cy={y + r + 6} rx={r * 0.8} ry={r * 0.26} fill="#28344a" opacity={0.12} />
      <g>
        <defs>
          <radialGradient id={`ball${Math.round(x)}`} cx="0.35" cy="0.3" r="0.9">
            <stop offset="0" stopColor="#ff8a52" />
            <stop offset="0.6" stopColor="#ff5a1f" />
            <stop offset="1" stopColor="#e0451a" />
          </radialGradient>
        </defs>
        <circle cx={x} cy={y} r={r} fill={`url(#ball${Math.round(x)})`} />
        <g fill="none" stroke="#a5310f" strokeWidth={r * 0.07}>
          <line x1={x - r} y1={y} x2={x + r} y2={y} />
          <line x1={x} y1={y - r} x2={x} y2={y + r} />
          <path d={`M ${x - r * 0.98} ${y - r * 0.2} Q ${x} ${y + r * 0.25} ${x + r * 0.98} ${y - r * 0.2}`} />
          <path d={`M ${x - r * 0.98} ${y + r * 0.2} Q ${x} ${y - r * 0.25} ${x + r * 0.98} ${y + r * 0.2}`} />
        </g>
        <ellipse cx={x - r * 0.34} cy={y - r * 0.38} rx={r * 0.28} ry={r * 0.18} fill="#fff" opacity={0.28} />
      </g>
    </g>
  );
}

/** Marca de balón compacta para el logotipo del sidebar / cabeceras. */
export function BrandMark({ size = 26 }: { size?: number }) {
  const r = size / 2 - 1;
  const c = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="brand-mark" xmlns="http://www.w3.org/2000/svg">
      <circle cx={c} cy={c} r={r} fill="#ff5a1f" />
      <g fill="none" stroke="#a5310f" strokeWidth={size * 0.06}>
        <line x1={c - r} y1={c} x2={c + r} y2={c} />
        <line x1={c} y1={c - r} x2={c} y2={c + r} />
        <path d={`M ${c - r * 0.98} ${c - r * 0.22} Q ${c} ${c + r * 0.28} ${c + r * 0.98} ${c - r * 0.22}`} />
        <path d={`M ${c - r * 0.98} ${c + r * 0.22} Q ${c} ${c - r * 0.28} ${c + r * 0.98} ${c + r * 0.22}`} />
      </g>
      <ellipse cx={c - r * 0.32} cy={c - r * 0.36} rx={r * 0.26} ry={r * 0.17} fill="#fff" opacity={0.3} />
    </svg>
  );
}

/** Podio isométrico con balón — identidad del fantasy. */
export function IsoTrophy({ size = 220 }: { size?: number }) {
  const s = 12, ox = size / 2, oy = 70;
  const P = (x: number, y: number, z = 0) => project(x, y, z, s, ox, oy);
  const pt = (a: readonly [number, number]) => `${a[0].toFixed(1)},${a[1].toFixed(1)}`;
  const poly = (...c: (readonly [number, number])[]) => c.map(pt).join(" ");

  function block(cx: number, cy: number, h: number, top: string, left: string, right: string) {
    const w = 1.5;
    const a = P(cx - w, cy - w, h), b = P(cx + w, cy - w, h), c = P(cx + w, cy + w, h), d = P(cx - w, cy + w, h);
    const b0 = P(cx + w, cy - w, 0), c0 = P(cx + w, cy + w, 0), d0 = P(cx - w, cy + w, 0);
    return (
      <g>
        <polygon points={poly(d, c, c0, d0)} fill={left} />
        <polygon points={poly(c, b, b0, c0)} fill={right} />
        <polygon points={poly(a, b, c, d)} fill={top} />
      </g>
    );
  }
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="iso" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx={ox} cy={oy + 132} rx={92} ry={22} fill="#28344a" opacity={0.08} />
      {/* 2º (izq), 1º (centro, alto), 3º (der) */}
      {block(-3, 0, 3.4, "#4a6fb0", "#33528c", "#3d61a2")}
      {block(3, 0, 2.2, "#4a6fb0", "#33528c", "#3d61a2")}
      {block(0, 0, 5.0, "#3f7be0", "#2b5bb5", "#356bcf")}
      <IsoBall x={ox} y={oy - 6} r={19} className="floaty" />
    </svg>
  );
}

/** Media pista vertical (canasta arriba) para la formación del fantasy — tema oscuro. */
export function HalfCourtBg({ className }: { className?: string }) {
  const W = 400, H = 330, cx = W / 2;
  const hoopY = 40;
  const keyW = 120, keyH = 130, keyX = cx - keyW / 2, keyY = hoopY;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={"court-svg " + (className ?? "")} xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="facourt" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1b2942" />
          <stop offset="1" stopColor="#111c30" />
        </linearGradient>
      </defs>
      <rect x="6" y="6" width={W - 12} height={H - 12} rx="18" fill="url(#facourt)" stroke="rgba(255,255,255,0.08)" strokeWidth="1.5" />
      <g fill="none" stroke="rgba(255,176,32,0.42)" strokeWidth="2">
        <rect x={keyX} y={keyY} width={keyW} height={keyH} />
        <path d={`M ${keyX} ${keyY + keyH} A ${keyW / 2} ${keyW / 2} 0 0 0 ${keyX + keyW} ${keyY + keyH}`} />
        <line x1={cx - 30} y1={hoopY} x2={cx + 30} y2={hoopY} strokeWidth="3" />
        <circle cx={cx} cy={hoopY + 12} r="9" strokeWidth="2.4" />
        <path d={`M 40 ${hoopY} L 40 ${hoopY + 60} A 150 150 0 0 0 ${W - 40} ${hoopY + 60} L ${W - 40} ${hoopY}`} />
        <path d={`M ${cx - 46} ${H - 6} A 46 46 0 0 1 ${cx + 46} ${H - 6}`} />
      </g>
    </svg>
  );
}

/** Escena isométrica pequeña para estados vacíos (portapapeles de scouting). */
export function IsoClipboard({ size = 200 }: { size?: number }) {
  const s = 11, ox = size / 2, oy = 40;
  const P = (x: number, y: number, z = 0) => project(x, y, z, s, ox, oy);
  const pt = (a: readonly [number, number]) => `${a[0].toFixed(1)},${a[1].toFixed(1)}`;
  const poly = (...c: (readonly [number, number])[]) => c.map(pt).join(" ");
  const a = P(-4, -4), b = P(4, -4), cc = P(4, 4), d = P(-4, 4);
  const t = 7;
  const be = [b[0], b[1] + t] as const, ce = [cc[0], cc[1] + t] as const, de = [d[0], d[1] + t] as const;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="iso" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx={ox} cy={oy + 118} rx={78} ry={20} fill="#28344a" opacity={0.08} />
      <polygon points={poly(d, cc, ce, de)} fill="#c79f5c" />
      <polygon points={poly(cc, b, be, ce)} fill="#b98a3d" />
      <polygon points={poly(a, b, cc, d)} fill="#2c3a53" stroke="#1f2a3d" strokeWidth={1.4} />
      {/* "papel" de scouting */}
      <g transform={`translate(0,-6)`}>
        <polygon points={poly(P(-2.6, -2.6), P(2.6, -2.6), P(2.6, 2.6), P(-2.6, 2.6))} fill="#fbf7ef" stroke="#d9cfbc" strokeWidth={1} />
      </g>
      <IsoBall x={ox + 44} y={oy + 82} r={15} />
    </svg>
  );
}
