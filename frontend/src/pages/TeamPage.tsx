import { useNavigate, useParams, Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import ShotChart from "../components/ShotChart";

function StatBox({ k, v, tone }: { k: string; v: any; tone?: string }) {
  return (
    <div className="stat-box">
      <div className={"v " + (tone ?? "")}>{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

export default function TeamPage() {
  const { id } = useParams();
  const tid = Number(id);
  const nav = useNavigate();
  const team = useAsync<any>(() => api.team(tid), [tid]);
  const shots = useAsync<any>(() => api.shotsTeam(tid), [tid]);

  if (team.loading) return <div className="loader">Cargando equipo…</div>;
  if (!team.data) return <div className="loader">No encontrado</div>;
  const t = team.data;
  const r = t.record;
  const sh = t.shooting;

  return (
    <div>
      <Link to="/" className="muted">← Rankings</Link>
      <h1 className="page-title" style={{ marginTop: 8 }}>
        {t.logo && <img className="team-logo" src={t.logo} style={{ width: 34, height: 34 }} />}
        {t.name}
      </h1>
      <p className="page-sub">{t.competition}{t.grupo ? ` · ${t.grupo}` : ""}</p>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <StatBox k="Balance" v={`${r.wins}-${r.losses}`} />
        <StatBox k="Puntos a favor" v={r.pts_for_avg} />
        <StatBox k="Puntos en contra" v={r.pts_against_avg} />
        <StatBox k="Diferencial" v={`${r.diff_avg >= 0 ? "+" : ""}${r.diff_avg}`} tone={r.diff_avg >= 0 ? "pos" : "neg"} />
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Tiro del equipo (partidos con detalle)</h3>
          <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
            <StatBox k="T2%" v={sh.fg2_pct} />
            <StatBox k="T3%" v={sh.fg3_pct} />
            <StatBox k="TL%" v={sh.ft_pct} />
          </div>
          <div className="stat-grid" style={{ gridTemplateColumns: "repeat(3,1fr)", marginTop: 12 }}>
            <StatBox k="Rebotes" v={sh.reb_total} />
            <StatBox k="Asistencias" v={sh.assists} />
            <StatBox k="Pérdidas" v={sh.turnovers} />
          </div>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Mapa de tiro acumulado</h3>
          {shots.loading ? <div className="loader">Cargando…</div> :
            (shots.data?.shots.length ? <ShotChart shots={shots.data.shots} /> :
              <div className="loader">Sin tiros con detalle todavía</div>)}
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Plantilla</h3>
        <table>
          <thead>
            <tr>
              <th>Jugador</th><th className="num">PJ</th><th className="num">MIN</th><th className="num">PTS</th>
              <th className="num">REB</th><th className="num">AST</th><th className="num">VAL</th>
              <th className="num">+/-</th><th className="num">T2%</th><th className="num">T3%</th>
            </tr>
          </thead>
          <tbody>
            {t.roster.map((p: any) => (
              <tr key={p.player_id} className="clickable" onClick={() => nav(`/player/${p.player_id}`)}>
                <td>{p.name}</td>
                <td className="num">{p.games}</td>
                <td className="num">{p.min_avg}</td>
                <td className="num" style={{ fontWeight: 700 }}>{p.ppg}</td>
                <td className="num">{p.rpg}</td>
                <td className="num">{p.apg}</td>
                <td className="num">{p.val_avg}</td>
                <td className={"num " + (p.plus_minus_avg >= 0 ? "pos" : "neg")}>
                  {p.plus_minus_avg >= 0 ? "+" : ""}{p.plus_minus_avg}
                </td>
                <td className="num">{p.fg2_pct}</td>
                <td className="num">{p.fg3_pct}</td>
              </tr>
            ))}
            {t.roster.length === 0 && <tr><td colSpan={10} className="muted">Sin partidos con detalle ingeridos</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
