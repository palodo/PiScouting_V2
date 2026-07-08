import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { useAuth } from "../auth";

export default function MyTeam() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [sim, setSim] = useState<number | null>(null);
  const dash = useAsync<any>(() => api.dashboard(sim ?? undefined), [user?.team?.team_id, sim]);

  if (dash.loading && !dash.data) return <div className="loader">Cargando tu equipo…</div>;
  if (dash.error) return <div className="loader">Elige tu equipo en Ajustes.</div>;
  const d = dash.data;
  const r = d.record;
  const next = d.next;
  const played = d.schedule.filter((s: any) => s.my_score !== null);
  const upcoming = d.schedule.filter((s: any) => s.my_score === null);
  const totalJ = d.total_jornadas || 34;

  return (
    <div>
      <h1 className="page-title">
        {d.team.logo && <img className="team-logo" src={d.team.logo} style={{ width: 34, height: 34 }} />}
        {d.team.name}
      </h1>
      <p className="page-sub">{d.team.competition}{d.team.grupo ? ` · ${d.team.grupo}` : ""} · Tu equipo</p>

      {/* Simulador de jornada */}
      <div className="card sim-bar">
        <label style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input type="checkbox" checked={sim !== null}
            onChange={(e) => setSim(e.target.checked ? Math.round(totalJ / 2) : null)} />
          <b>🗓 Simular mitad de temporada</b>
        </label>
        {sim !== null && (
          <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1 }}>
            <span className="muted">Tras jornada</span>
            <input type="range" min={1} max={totalJ - 1} value={sim}
              onChange={(e) => setSim(Number(e.target.value))} style={{ flex: 1 }} />
            <span className="chip">J{sim} / {totalJ}</span>
          </div>
        )}
      </div>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <div className="stat-box"><div className="v">{r.wins}-{r.losses}</div><div className="k">Balance{sim !== null ? ` (J1-${sim})` : ""}</div></div>
        <div className="stat-box"><div className="v">{r.pts_for_avg}</div><div className="k">Puntos a favor</div></div>
        <div className="stat-box"><div className="v">{r.pts_against_avg}</div><div className="k">Puntos en contra</div></div>
        <div className="stat-box"><div className={"v " + (r.diff_avg >= 0 ? "pos" : "neg")}>{r.diff_avg >= 0 ? "+" : ""}{r.diff_avg}</div><div className="k">Diferencial</div></div>
      </div>

      {/* Próximo rival */}
      <div className="card next-rival">
        <div className="k" style={{ marginBottom: 8 }}>PRÓXIMO RIVAL{next ? ` · ${next.jornada}` : ""}</div>
        {next ? (
          <div className="next-body">
            <div>
              {next.opponent_logo && <img className="team-logo" src={next.opponent_logo} style={{ width: 42, height: 42 }} />}
              <div>
                <div style={{ fontSize: 20, fontWeight: 800 }}>{next.opponent}</div>
                <div className="muted">{next.is_home ? "🏠 En casa" : "✈️ Fuera"} · {next.date ?? ""}</div>
              </div>
            </div>
            <button className="primary-btn" onClick={() => nav(`/scout/${next.opponent_id}`)}>
              🔍 Ver scouting del rival
            </button>
          </div>
        ) : (
          <div>
            <p className="muted" style={{ marginTop: 0 }}>
              {sim !== null ? "No hay más partidos tras esa jornada." : "Temporada finalizada — no hay próximo partido. Activa «Simular mitad de temporada» o elige un rival de la clasificación."}
            </p>
            <Link to="/rankings" className="primary-btn" style={{ display: "inline-block", textDecoration: "none" }}>Ver clasificación</Link>
          </div>
        )}
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Resultados</h3>
          <table>
            <thead><tr><th>J</th><th>Rival</th><th className="num">Res.</th><th></th></tr></thead>
            <tbody>
              {played.map((s: any) => (
                <tr key={s.match_id} className="clickable" onClick={() => nav(`/match/${s.match_id}`)}>
                  <td>{s.jornada_num}</td>
                  <td>{s.is_home ? "" : "@ "}{s.opponent}</td>
                  <td className="num">{s.my_score}-{s.their_score}</td>
                  <td><span style={{ color: s.result === "V" ? "var(--win)" : "var(--loss)", fontWeight: 800 }}>{s.result}</span></td>
                </tr>
              ))}
              {played.length === 0 && <tr><td colSpan={4} className="muted">Aún sin partidos jugados.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>{sim !== null ? "Calendario por jugar" : "Calendario restante"}</h3>
          {upcoming.length === 0 ? <p className="muted">Temporada completa.</p> : (
            <table>
              <thead><tr><th>J</th><th>Rival</th><th>Local</th><th></th></tr></thead>
              <tbody>
                {upcoming.map((s: any) => (
                  <tr key={s.match_id} className="clickable" onClick={() => nav(`/scout/${s.opponent_id}`)}>
                    <td>{s.jornada_num}</td><td>{s.opponent}</td>
                    <td>{s.is_home ? "🏠" : "✈️"}</td>
                    <td className="muted">scout →</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
