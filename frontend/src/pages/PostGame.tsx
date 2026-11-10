import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, apiUrl } from "../api";
import { useAsync } from "../hooks";

/* ============================================================================
   Informe post-partido.

   Es el mismo informe que sale en PDF, pero en pantalla: la idea es poder mirarlo
   en el móvil camino del pabellón y descargarlo solo cuando hay que llevarlo impreso.
   Todo lo que se pinta aquí viene de /api/matches/{id}/postgame.
   ========================================================================== */

const fmt = (v: any, suffix = "") =>
  v === null || v === undefined ? "—" : `${String(v).replace(".", ",")}${suffix}`;

const signed = (v: number) => (v > 0 ? `+${v}` : String(v));
const cls = (v: number) => (v > 0 ? "pos" : v < 0 ? "neg" : "muted");

function Card({ label, value, foot }: { label: string; value: any; foot?: string }) {
  return (
    <div className="pg-card">
      <div className="pg-card-k">{label}</div>
      <div className="pg-card-v">{fmt(value)}</div>
      {foot && <div className="pg-card-f">{foot}</div>}
    </div>
  );
}

function Section({ n, kicker, title, children }: any) {
  return (
    <section className="pg-section">
      <div className="pg-kicker">{String(n).padStart(2, "0")} · {kicker}</div>
      <h2 className="pg-title">{title}</h2>
      {children}
    </section>
  );
}

/* --- gráfico de evolución del marcador, en SVG --- */
function FlowChart({ flow, home, away }: any) {
  const series: any[] = flow.series || [];
  if (series.length < 2) return null;
  const W = 900, H = 230, pad = { l: 34, r: 10, t: 10, b: 20 };
  const end = Math.max(...series.map((s) => s.t)) || 2400;
  const top = Math.max(12, Math.max(...series.map((s) => Math.abs(s.diff))) + 3);
  const X = (t: number) => pad.l + (t / end) * (W - pad.l - pad.r);
  const Y = (v: number) => pad.t + ((top - v) / (2 * top)) * (H - pad.t - pad.b);

  // escalera: el marcador salta, no interpola
  let d = `M ${X(series[0].t)} ${Y(series[0].diff)}`;
  let area = `M ${X(series[0].t)} ${Y(0)} L ${X(series[0].t)} ${Y(series[0].diff)}`;
  series.slice(1).forEach((s) => {
    d += ` H ${X(s.t)} V ${Y(s.diff)}`;
    area += ` H ${X(s.t)} V ${Y(s.diff)}`;
  });
  area += ` V ${Y(0)} Z`;
  const quarters = [];
  for (let q = 600; q < end; q += 600) quarters.push(q);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pg-flow" role="img"
         aria-label="Evolución de la diferencia de marcador">
      <defs>
        <clipPath id="pg-up"><rect x="0" y="0" width={W} height={Y(0)} /></clipPath>
        <clipPath id="pg-dn"><rect x="0" y={Y(0)} width={W} height={H - Y(0)} /></clipPath>
      </defs>
      {[top, top / 2, -top / 2, -top].map((v) => (
        <line key={v} x1={pad.l} x2={W - pad.r} y1={Y(v)} y2={Y(v)} stroke="var(--border)" />
      ))}
      {[top, top / 2, 0, -top / 2, -top].map((v) => (
        <text key={`t${v}`} x={pad.l - 6} y={Y(v) + 3} textAnchor="end"
              fontSize="9" fill="var(--muted)">{v > 0 ? `+${Math.round(v)}` : Math.round(v)}</text>
      ))}
      {quarters.map((q) => (
        <line key={q} x1={X(q)} x2={X(q)} y1={pad.t} y2={H - pad.b} stroke="var(--border)" />
      ))}
      <path d={area} fill="rgba(35,164,85,.18)" clipPath="url(#pg-up)" />
      <path d={area} fill="rgba(224,86,75,.16)" clipPath="url(#pg-dn)" />
      <line x1={pad.l} x2={W - pad.r} y1={Y(0)} y2={Y(0)} stroke="var(--muted)" />
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" />
      {quarters.concat([end]).map((q, i) => (
        <text key={`q${i}`} x={X(q) - 24} y={H - 6} fontSize="9" fill="var(--muted)">
          {`Q${i + 1}`}
        </text>
      ))}
      <text x={pad.l + 4} y={pad.t + 10} fontSize="9.5" fill="var(--made)">▲ {home}</text>
      <text x={pad.l + 4} y={H - pad.b - 4} fontSize="9.5" fill="var(--miss)">▼ {away}</text>
    </svg>
  );
}

/* --- mapa de tiro con la geometría calibrada del backend --- */
const COURT_L = 13.5, COURT_W = 16.3, HOOP_D = 1.575, R3 = 6.75, CY = 6.6;
const CD = HOOP_D + Math.sqrt(R3 * R3 - CY * CY);

function ShotMap({ shots }: { shots: any[] }) {
  const M = 26;                       // píxeles por metro
  const W = COURT_W * M, H = COURT_L * M;
  const PX = (dy: number) => W / 2 + dy * M;
  const PY = (depth: number) => H - depth * M;
  const pos = (s: any) => {
    const depth = ((100 - s.hx) / 100) * COURT_L;
    const dy = ((s.hy - 50) / 100) * COURT_W;
    return [PX(dy), PY(depth)];
  };
  const stroke = "var(--court-line)";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pg-court" role="img" aria-label="Mapa de tiro">
      <rect x="0" y="0" width={W} height={H} fill="var(--court-bg)" />
      <g fill="none" stroke={stroke} strokeWidth="1.5">
        <rect x={PX(-7.5)} y={PY(COURT_L)} width={15 * M} height={COURT_L * M} />
        <rect x={PX(-2.45)} y={PY(5.8)} width={4.9 * M} height={5.8 * M} />
        <path d={`M ${PX(-1.8)} ${PY(5.8)} A ${1.8 * M} ${1.8 * M} 0 0 0 ${PX(1.8)} ${PY(5.8)}`} />
        <line x1={PX(-0.9)} y1={PY(1.2)} x2={PX(0.9)} y2={PY(1.2)} strokeWidth="2.2" />
        <circle cx={PX(0)} cy={PY(HOOP_D)} r={0.225 * M} />
        <path d={`M ${PX(-CY)} ${PY(0)} L ${PX(-CY)} ${PY(CD)}
                  A ${R3 * M} ${R3 * M} 0 0 0 ${PX(CY)} ${PY(CD)}
                  L ${PX(CY)} ${PY(0)}`} />
      </g>
      {shots.map((s, i) => {
        const [x, y] = pos(s);
        return s.made ? (
          <circle key={i} cx={x} cy={y} r={4.5} fill="var(--made)" stroke="#fff" strokeWidth="1" />
        ) : (
          <g key={i} stroke="var(--miss)" strokeWidth="2">
            <line x1={x - 4} y1={y - 4} x2={x + 4} y2={y + 4} />
            <line x1={x - 4} y1={y + 4} x2={x + 4} y2={y - 4} />
          </g>
        );
      })}
    </svg>
  );
}

function Bar({ label, value, max, color }: any) {
  const pct = Math.max(2, Math.min(100, ((value || 0) / max) * 100));
  return (
    <div className="pg-bar">
      <span className="pg-bar-k">{label}</span>
      <span className="pg-bar-track"><i style={{ width: `${pct}%`, background: color }} /></span>
      <b>{fmt(value)}</b>
    </div>
  );
}

function BoxTable({ rows, totals }: any) {
  return (
    <div className="table-scroll">
      <table className="pg-box">
        <thead>
          <tr>
            <th>Jugador</th><th className="num">Min</th><th className="num">Pts</th>
            <th className="num">TC</th><th className="num">T3</th><th className="num">TL</th>
            <th className="num">RO</th><th className="num">RD</th><th className="num">AS</th>
            <th className="num">Pér</th><th className="num">Rob</th><th className="num">FC</th>
            <th className="num">Val</th><th className="num">+/-</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b: any) => (
            <tr key={b.player_id}>
              <td>
                <span className="pg-dorsal">#{b.dorsal || "—"}</span> {b.name}
                {b.starter && <span className="pg-tit">TIT</span>}
              </td>
              <td className="num">{b.min}</td>
              <td className="num" style={{ fontWeight: 700 }}>{b.pts}</td>
              <td className="num">{b.tc}</td><td className="num">{b.t3}</td>
              <td className="num">{b.tl}</td><td className="num">{b.oreb}</td>
              <td className="num">{b.dreb}</td><td className="num">{b.ast}</td>
              <td className="num">{b.tov}</td><td className="num">{b.stl}</td>
              <td className="num">{b.pf}</td><td className="num">{b.val}</td>
              <td className={"num " + cls(b.plus_minus)}>{signed(b.plus_minus)}</td>
            </tr>
          ))}
          <tr className="pg-total">
            <td>Totales</td><td className="num" /><td className="num">{totals.pts}</td>
            <td className="num">{totals.tc}</td><td className="num">{totals.t3}</td>
            <td className="num">{totals.tl}</td><td className="num">{totals.oreb}</td>
            <td className="num">{totals.dreb}</td><td className="num">{totals.ast}</td>
            <td className="num">{totals.tov}</td><td className="num">{totals.stl}</td>
            <td className="num">{totals.pf}</td><td className="num" /><td className="num" />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function PostGame() {
  const { id } = useParams();
  const mid = Number(id);
  const nav = useNavigate();
  const [downloading, setDownloading] = useState(false);
  const [side, setSide] = useState<"home" | "away">("home");
  const rep = useAsync<any>(() => api.postgame(mid), [mid]);

  async function downloadPdf() {
    setDownloading(true);
    try {
      const res = await fetch(apiUrl(`/matches/${mid}/postgame/pdf`));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `informe_${mid}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  }

  if (rep.loading)
    return <div className="loader">Montando el informe… (si es la primera vez,
      hay que descargar el play-by-play del partido)</div>;
  if (rep.error) return <div className="loader">No se pudo montar el informe: {String(rep.error)}</div>;
  if (!rep.data) return <div className="loader">No encontrado</div>;

  const d = rep.data;
  const mt = d.match, adv = d.advanced, sm = d.summary;
  const hn = mt.home.name, an = mt.away.name;
  const teamName = (s: string) => (s === "home" ? hn : an);

  return (
    <div className="postgame">
      {/* ---------- cabecera ---------- */}
      <div className="pg-head">
        <div>
          <div className="chip">INFORME POST-PARTIDO</div>
          <h1 className="page-title" style={{ marginTop: 8 }}>
            <span className={mt.winner === "home" ? "" : "muted"}>{hn}</span>
            {" "}<b className="pg-score">{mt.home.score}–{mt.away.score}</b>{" "}
            <span className={mt.winner === "away" ? "" : "muted"}>{an}</span>
          </h1>
          <p className="page-sub" style={{ margin: 0 }}>
            {[mt.competition, mt.grupo, mt.jornada, mt.date].filter(Boolean).join(" · ")}
            {mt.venue ? ` · ${mt.venue}` : ""}
          </p>
          <p className="pg-quarters">
            {mt.quarters.map((q: any) => (
              <span key={q.n}><b>Q{q.n}</b> {q.home}-{q.away}</span>
            ))}
            {mt.halftime && <span className="muted">Descanso {mt.halftime}</span>}
          </p>
        </div>
        <div className="scout-actions">
          <button className="primary-btn" onClick={downloadPdf} disabled={downloading}>
            {downloading ? "Generando PDF…" : "📄 Descargar informe PDF"}
          </button>
          <button className="ghost-btn" onClick={() => nav(`/match/${mid}`)}>Ver partido</button>
        </div>
      </div>

      {/* ---------- 01 resumen ---------- */}
      <Section n={1} kicker="Resumen ejecutivo" title={sm.headline}>
        <div className="pg-lead">{sm.lead}</div>
        <div className="pg-cards">
          {sm.cards.map((c: any, i: number) => (
            <Card key={i} label={c.label} value={c.value} foot={c.foot} />
          ))}
        </div>
        <div className="grid grid-2" style={{ marginTop: 14 }}>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Qué decidió el partido</h3>
            {sm.decided.map((x: any, i: number) => (
              <p key={i}><b>{x.title}.</b> {x.text}</p>
            ))}
          </div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Señales de juego</h3>
            {sm.signals.map((x: any, i: number) => (
              <p key={i}><b>{x.title}:</b> {x.text}</p>
            ))}
          </div>
        </div>
      </Section>

      {/* ---------- 02 evolución ---------- */}
      {d.flow && (
        <Section n={2} kicker="Evolución del marcador"
                 title={`${d.flow.lead_time.home >= d.flow.lead_time.away ? hn : an} mandó ${
                   d.flow.lead_time.home >= d.flow.lead_time.away
                     ? d.flow.lead_time.home_label : d.flow.lead_time.away_label} de los 40 minutos`}>
          <div className="card">
            <FlowChart flow={d.flow} home={hn} away={an} />
          </div>
          <div className="pg-cards">
            <Card label={`${hn} por delante`} value={d.flow.lead_time.home_label}
                  foot={`máx. +${d.flow.max_lead.home.pts} · ${d.flow.max_lead.home.at}`} />
            <Card label={`${an} por delante`} value={d.flow.lead_time.away_label}
                  foot={`máx. +${d.flow.max_lead.away.pts} · ${d.flow.max_lead.away.at}`} />
            <Card label="Cambios de líder" value={d.flow.lead_changes}
                  foot={`${d.flow.ties} empate(s)`} />
            <Card label="Sequía más larga del local" value={d.flow.droughts.home.label}
                  foot={`desde ${d.flow.droughts.home.from}`} />
            <Card label="Sequía más larga del visitante" value={d.flow.droughts.away.label}
                  foot={`desde ${d.flow.droughts.away.from}`} />
          </div>
          {d.flow.runs.length > 0 && (
            <div className="card" style={{ marginTop: 14 }}>
              <h3 style={{ marginTop: 0 }}>Rachas sin respuesta (6+ puntos)</h3>
              <table>
                <thead><tr><th>Equipo</th><th>Parcial</th><th>Marcador</th><th>Reloj</th></tr></thead>
                <tbody>
                  {d.flow.runs.map((r: any, i: number) => (
                    <tr key={i}>
                      <td><b>{r.is_home ? hn : an}</b></td>
                      <td>{r.run}</td>
                      <td>{r.from_score} → {r.to_score}</td>
                      <td className="muted">{r.from_clock} → {r.to_clock}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* ---------- 03 fases ---------- */}
      {d.phases && (
        <Section n={3} kicker="Fases y tiempos muertos" title="Arranques, tramos centrales y cierres">
          <div className="grid grid-2">
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Cada cuarto por tramos</h3>
              <table>
                <thead>
                  <tr><th>Periodo</th><th>Primeros 3'</th><th>Tramo central</th>
                      <th>Últimos 2'</th><th className="num">Cuarto</th></tr>
                </thead>
                <tbody>
                  {d.phases.quarters.map((q: any) => (
                    <tr key={q.quarter}>
                      <td><b>Q{q.quarter}</b></td>
                      <td>{q.open3} <i className={cls(q.open3_diff)}>({signed(q.open3_diff)})</i></td>
                      <td>{q.mid} <i className={cls(q.mid_diff)}>({signed(q.mid_diff)})</i></td>
                      <td>{q.close2} <i className={cls(q.close2_diff)}>({signed(q.close2_diff)})</i></td>
                      <td className="num"><b>{q.total}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 12 }}>Parciales {hn}-{an}.</p>
            </div>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Tiempos muertos</h3>
              <table>
                <thead>
                  <tr><th>Pide</th><th>Reloj</th><th>Marcador</th>
                      <th>2' antes</th><th>2' después</th><th className="num">Saldo</th></tr>
                </thead>
                <tbody>
                  {d.phases.timeouts.map((t: any, i: number) => (
                    <tr key={i}>
                      <td><b>{t.is_home ? hn : an}</b></td>
                      <td className="muted">{t.at}</td><td>{t.score}</td>
                      <td>{t.before}</td><td>{t.after}</td>
                      <td className={"num " + cls(t.swing)}>{signed(t.swing)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 12 }}>
                Desde el punto de vista de quien lo pide. Muestra pequeña: lectura descriptiva.
              </p>
            </div>
          </div>
        </Section>
      )}

      {/* ---------- 04 avanzada ---------- */}
      <Section n={4} kicker="Estadística avanzada" title="Quién ganó cada uno de los cuatro factores">
        <div className="grid grid-2">
          <div className="card">
            <table>
              <thead><tr><th>Métrica</th><th className="num">{hn}</th><th className="num">{an}</th></tr></thead>
              <tbody>
                {[
                  ["Posesiones reales", adv.home.poss_real, adv.away.poss_real],
                  ["Posesiones estimadas", adv.home.poss_est, adv.away.poss_est],
                  ["Ef. ofensiva (pts/100)", adv.home.off_rtg, adv.away.off_rtg],
                  ["Ef. defensiva", adv.home.def_rtg, adv.away.def_rtg],
                  ["eFG%", adv.home.efg, adv.away.efg],
                  ["TS%", adv.home.ts, adv.away.ts],
                  ["TOV%", adv.home.tov_pct, adv.away.tov_pct],
                  ["ORB%", adv.home.orb_pct, adv.away.orb_pct],
                  ["DRB%", adv.home.drb_pct, adv.away.drb_pct],
                  ["FTr", adv.home.ftr, adv.away.ftr],
                  ["Volumen de triple", adv.home.three_rate, adv.away.three_rate],
                  ["% canastas asistidas", adv.home.ast_pct, adv.away.ast_pct],
                ].map(([k, a, b]: any) => (
                  <tr key={k}><td>{k}</td><td className="num">{fmt(a)}</td><td className="num">{fmt(b)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Four Factors</h3>
            {[["eFG%", "efg", 70, "mayor es mejor"], ["TOV%", "tov_pct", 30, "menor es mejor"],
              ["ORB%", "orb_pct", 55, "mayor es mejor"], ["FTr", "ftr", 60, "mayor es mejor"]]
              .map(([label, key, max, hint]: any) => (
                <div key={key} className="pg-ff">
                  <div className="pg-ff-head"><b>{label}</b><span className="muted">{hint}</span></div>
                  <Bar label={hn} value={adv.home[key]} max={max} color="var(--accent)" />
                  <Bar label={an} value={adv.away[key]} max={max} color="var(--wood)" />
                </div>
              ))}
            <p className="muted" style={{ fontSize: 12 }}>
              Las eficiencias van sobre el ritmo del partido ({fmt(adv.pace)} posesiones),
              el mismo para los dos. TOV%, ORB% y FTr, sobre las posesiones propias.
            </p>
          </div>
        </div>
      </Section>

      {/* ---------- 05 economía ---------- */}
      {d.possessions && (
        <Section n={5} kicker="Economía de posesión" title="De dónde salieron los puntos">
          <div className="pg-cards">
            <Card label="Pts 2ª oportunidad"
                  value={`${d.possessions.home.second_chance}-${d.possessions.away.second_chance}`}
                  foot={`en ${d.possessions.home.second_chance_poss}-${d.possessions.away.second_chance_poss} posesiones`} />
            <Card label="Pts tras pérdida"
                  value={`${d.possessions.home.off_turnovers}-${d.possessions.away.off_turnovers}`}
                  foot={`en ${d.possessions.home.off_turnovers_poss}-${d.possessions.away.off_turnovers_poss} posesiones`} />
            <Card label="Pts rápidos (hasta 8 s)"
                  value={`${d.possessions.home.fast_break}-${d.possessions.away.fast_break}`}
                  foot={`posesión media ${fmt(d.possessions.home.avg_seconds)}s / ${fmt(d.possessions.away.avg_seconds)}s`} />
            <Card label="Posesiones vacías"
                  value={`${d.possessions.home.empty}/${d.possessions.home.poss}`}
                  foot={`${an}: ${d.possessions.away.empty}/${d.possessions.away.poss}`} />
          </div>
          <div className="grid grid-2" style={{ marginTop: 14 }}>
            {(["home", "away"] as const).map((s) => (
              <div className="card" key={s}>
                <h3 style={{ marginTop: 0 }}>{teamName(s)} · puntos por posesión</h3>
                {d.possessions[s].by_origin.map((o: any) => (
                  <div key={o.origin}>
                    <div className="pg-origin">{o.label}
                      <span className="muted"> · {o.pts} pts en {o.poss} pos.</span></div>
                    <Bar label="" value={o.ppp} max={1.6}
                         color={s === "home" ? "var(--accent)" : "var(--wood)"} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ---------- 06 tiro ---------- */}
      {d.shooting && (d.shooting.shots.home.length > 0 || d.shooting.shots.away.length > 0) && (
        <Section n={6} kicker="Perfil de tiro" title="Dónde tiró cada equipo y qué sacó de cada zona">
          <div className="grid grid-2">
            {(["home", "away"] as const).map((s) => (
              <div className="card" key={s}>
                <h3 style={{ marginTop: 0 }}>Mapa de tiro · {teamName(s)}</h3>
                <ShotMap shots={d.shooting.shots[s]} />
              </div>
            ))}
          </div>
          <div className="card" style={{ marginTop: 14 }}>
            <table>
              <thead>
                <tr><th>Zona</th>
                  <th className="num">{hn} TC</th><th className="num">Pts/tiro</th><th className="num">Vol.</th>
                  <th className="num">{an} TC</th><th className="num">Pts/tiro</th><th className="num">Vol.</th></tr>
              </thead>
              <tbody>
                {d.shooting.zones.home.map((z: any, i: number) => {
                  const b = d.shooting.zones.away[i];
                  return (
                    <tr key={z.zone}>
                      <td><b>{z.label}</b></td>
                      <td className="num">{z.made}/{z.att}</td>
                      <td className="num">{fmt(z.pps)}</td><td className="num">{z.share}%</td>
                      <td className="num">{b.made}/{b.att}</td>
                      <td className="num">{fmt(b.pps)}</td><td className="num">{b.share}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 12 }}>
              Verde = anotado, rojo = fallado. Zonas FIBA sobre las coordenadas de la FEB,
              calibradas contra el valor real de cada tiro.
            </p>
          </div>
        </Section>
      )}

      {/* ---------- 07 impacto ---------- */}
      <Section n={7} kicker="Impacto, banquillo y faltas" title="Quién movió el partido">
        <div className="grid grid-2">
          {(["home", "away"] as const).map((s) => (
            <div className="card" key={s}>
              <h3 style={{ marginTop: 0 }}>Top 3 · {teamName(s)}</h3>
              <table>
                <thead><tr><th>Jugador</th><th className="num">Min</th><th className="num">Game Score</th>
                  <th className="num">Val</th><th className="num">Pts</th><th className="num">+/-</th></tr></thead>
                <tbody>
                  {d.impact.top[s].map((t: any, i: number) => (
                    <tr key={i}>
                      <td><b>{t.short}</b></td><td className="num">{t.min}</td>
                      <td className="num">{fmt(t.gmsc)}</td><td className="num">{t.val}</td>
                      <td className="num">{t.pts}</td>
                      <td className={"num " + cls(t.plus_minus)}>{signed(t.plus_minus)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
        {!d.starters?.length ? (
          <div className="card" style={{ marginTop: 14 }}>
            <p className="muted" style={{ margin: 0 }}>
              Titulares frente a suplentes no disponible: hace falta el play-by-play del
              partido, porque el acta de la FEB no publica quién salió de inicio.
            </p>
          </div>
        ) : (
        <div className="card" style={{ marginTop: 14 }}>
          <h3 style={{ marginTop: 0 }}>Titulares frente a suplentes</h3>
          <table>
            <thead><tr><th>Grupo</th><th className="num">Min</th><th className="num">Pts</th>
              <th className="num">% del equipo</th><th className="num">Pts/40</th>
              <th className="num">TS%</th><th className="num">Pérdidas</th></tr></thead>
            <tbody>
              {(["home", "away"] as const).flatMap((s) =>
                d.impact.units[s].map((u: any, i: number) => (
                  <tr key={`${s}${i}`}>
                    <td><b>{teamName(s)}</b> · {u.group}</td>
                    <td className="num">{u.min}</td><td className="num">{u.pts}</td>
                    <td className="num">{u.share}%</td><td className="num">{fmt(u.pts40)}</td>
                    <td className="num">{fmt(u.ts)}%</td><td className="num">{u.tov}</td>
                  </tr>
                )))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12 }}>
            La titularidad sale del play-by-play (los cinco del 10:00 del Q1): el acta de la
            FEB no publica ese campo.
          </p>
        </div>
        )}
      </Section>

      {/* ---------- 08 boxscore + producción + rotaciones ---------- */}
      <Section n={8} kicker="Jugadores" title="Box score, producción y rotaciones">
        <div className="pg-tabs">
          {(["home", "away"] as const).map((s) => (
            <button key={s} className={side === s ? "active" : ""} onClick={() => setSide(s)}>
              {teamName(s)}
            </button>
          ))}
        </div>

        <div className="card">
          <BoxTable rows={d.box[side]} totals={d.box.totals[side]} />
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3 style={{ marginTop: 0 }}>Producción individual</h3>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Jugador</th><th className="num">Min</th><th className="num">%Uso</th>
                <th className="num">TS%</th><th className="num">GmSc</th><th className="num">Pts prod.</th>
                <th className="num">Ef. of.</th><th className="num">Floor%</th>
                <th className="num">Stops</th><th className="num">+/-</th></tr></thead>
              <tbody>
                {d.production[side].map((p: any) => (
                  <tr key={p.player_id}>
                    <td><span className="pg-dorsal">#{p.dorsal || "—"}</span> {p.short}</td>
                    <td className="num">{fmt(p.min)}</td><td className="num">{fmt(p.usg)}%</td>
                    <td className="num">{fmt(p.ts, "%")}</td><td className="num">{fmt(p.gmsc)}</td>
                    <td className="num">{fmt(p.pprod)}</td><td className="num">{fmt(p.ortg)}</td>
                    <td className="num">{fmt(p.floor, "%")}</td><td className="num">{fmt(p.stops)}</td>
                    <td className={"num " + cls(p.plus_minus)}>{signed(p.plus_minus)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Puntos producidos, eficiencia individual, Floor% y Stops son estimaciones de
            Oliver (oliver_bref_v1): en un solo partido tienen mucha varianza. Eficiencia y
            Floor% solo con 10+ minutos.
          </p>
        </div>

        {d.lineups && (
          <div className="grid grid-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Quintetos con 1:48 o más</h3>
              <table>
                <thead><tr><th>Quinteto</th><th className="num">Min</th>
                  <th className="num">+/-</th><th className="num">Parcial</th></tr></thead>
                <tbody>
                  {d.lineups[side].units.map((u: any, i: number) => (
                    <tr key={i}>
                      <td style={{ fontSize: 12 }}>{u.players.join(" · ")}</td>
                      <td className="num">{u.min}</td>
                      <td className={"num " + cls(u.plus_minus)}>{signed(u.plus_minus)}</td>
                      <td className="num">{u.partial}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 12 }}>
                {d.lineups[side].distinct} quintetos distintos. Validados contra los minutos
                y el +/- oficiales, pero con muestras de pocos minutos: sirven para elegir
                vídeo, no para sentenciar.
              </p>
            </div>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Parejas y tríos</h3>
              <table>
                <thead><tr><th>Pareja</th><th className="num">Min</th><th className="num">+/-</th></tr></thead>
                <tbody>
                  {d.lineups[side].pairs.map((p: any, i: number) => (
                    <tr key={i}>
                      <td>{p.players.join(" + ")}</td><td className="num">{fmt(p.min)}</td>
                      <td className={"num " + cls(p.plus_minus)}>{signed(p.plus_minus)}</td>
                    </tr>
                  ))}
                  {d.lineups[side].trios.map((p: any, i: number) => (
                    <tr key={`t${i}`} className="pg-trio">
                      <td>{p.players.join(" + ")}</td><td className="num">{fmt(p.min)}</td>
                      <td className={"num " + cls(p.plus_minus)}>{signed(p.plus_minus)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      {/* ---------- 09 claves ---------- */}
      <Section n={9} kicker="Claves de scouting" title="Claves para preparar a cada equipo">
        <div className="grid grid-2">
          {(["home", "away"] as const).map((s) => (
            <div className="card" key={s}>
              <h3 style={{ marginTop: 0 }}>{d.keys[s].team}</h3>
              <p><b>Qué quitarle:</b> {d.keys[s].take_away.join("; ")}.</p>
              <p><b>Dónde atacarle:</b> {d.keys[s].attack.join("; ")}.</p>
              <p><b>A vigilar:</b> {d.keys[s].watch.join("; ")}.</p>
            </div>
          ))}
        </div>
      </Section>

      {/* ---------- 10 calidad ---------- */}
      <Section n={10} kicker="Calidad del dato" title="Qué podemos afirmar y qué sería falsamente preciso">
        <div className="grid grid-2">
          <div className="card pg-ok">
            <h3 style={{ marginTop: 0 }}>Verificado / reconciliado</h3>
            <ul>{d.quality.verified.map((v: string, i: number) => <li key={i}>{v}</li>)}</ul>
          </div>
          <div className="card pg-warn">
            <h3 style={{ marginTop: 0 }}>Estimado o limitado</h3>
            <ul>{d.quality.estimated.map((v: string, i: number) => <li key={i}>{v}</li>)}</ul>
          </div>
        </div>
        <div className="pg-criterio">
          <b>Criterio PiScouting.</b> Dato oficial, cálculo derivado y reconstrucción van
          separados. Lo validable se valida, lo estimado se etiqueta y lo que el feed no
          permite calcular se omite en vez de rellenarse.
        </div>
      </Section>
    </div>
  );
}
