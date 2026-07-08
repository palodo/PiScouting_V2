import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, TeamRow, LeaderRow } from "../api";
import { useAsync } from "../hooks";

const STATS: Record<string, string> = {
  pts: "Puntos", val: "Valoración", plus_minus: "+/-", treb: "Rebotes", ast: "Asistencias", stl: "Robos",
};

export default function Rankings() {
  const nav = useNavigate();
  const meta = useAsync(() => api.competitions(), []);
  const [competition, setCompetition] = useState<string>("");
  const [grupo, setGrupo] = useState<string>("");
  const [stat, setStat] = useState<string>("pts");

  useEffect(() => {
    if (meta.data && !competition && meta.data.competitions.length) {
      setCompetition(meta.data.competitions[0].competition);
    }
  }, [meta.data]);

  const grupos = meta.data?.competitions.find((c) => c.competition === competition)?.grupos ?? [];

  const teams = useAsync<TeamRow[]>(
    () => (competition ? api.rankingsTeams(competition, grupo || undefined) : Promise.resolve([])),
    [competition, grupo]
  );
  const leaders = useAsync<LeaderRow[]>(
    () => (competition ? api.rankingsPlayers(competition, stat, 15) : Promise.resolve([])),
    [competition, stat]
  );

  return (
    <div>
      <h1 className="page-title">Rankings</h1>
      <p className="page-sub">Clasificación y líderes estadísticos · Temporada 2025/26</p>

      <div className="toolbar">
        <select value={competition} onChange={(e) => { setCompetition(e.target.value); setGrupo(""); }}>
          {meta.data?.competitions.map((c) => (
            <option key={c.competition} value={c.competition}>{c.competition} ({c.teams})</option>
          ))}
        </select>
        {grupos.length > 1 && (
          <select value={grupo} onChange={(e) => setGrupo(e.target.value)}>
            <option value="">Todos los grupos</option>
            {grupos.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        )}
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Clasificación</h3>
          {teams.loading ? <div className="loader">Cargando…</div> : (
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Equipo</th><th className="num">PJ</th><th className="num">V-D</th>
                  <th className="num">PF</th><th className="num">PC</th><th className="num">+/-</th>
                </tr>
              </thead>
              <tbody>
                {teams.data?.map((t) => (
                  <tr key={t.team_id} className="clickable" onClick={() => nav(`/team/${t.team_id}`)}>
                    <td><span className="rank-badge">{t.rank}</span></td>
                    <td>{t.name}</td>
                    <td className="num">{t.games}</td>
                    <td className="num wl"><span className="w">{t.wins}</span>-<span className="l">{t.losses}</span></td>
                    <td className="num">{t.pts_for_avg}</td>
                    <td className="num">{t.pts_against_avg}</td>
                    <td className={"num " + (t.diff_avg >= 0 ? "pos" : "neg")}>
                      {t.diff_avg >= 0 ? "+" : ""}{t.diff_avg}
                    </td>
                  </tr>
                ))}
                {teams.data?.length === 0 && <tr><td colSpan={7} className="muted">Sin datos</td></tr>}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="toolbar" style={{ marginBottom: 12, justifyContent: "space-between" }}>
            <h3 style={{ margin: 0 }}>Líderes</h3>
            <select value={stat} onChange={(e) => setStat(e.target.value)}>
              {Object.entries(STATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          {leaders.loading ? <div className="loader">Cargando…</div> : (
            <table>
              <thead>
                <tr><th>#</th><th>Jugador</th><th>Equipo</th><th className="num">PJ</th><th className="num">Media</th></tr>
              </thead>
              <tbody>
                {leaders.data?.map((p, i) => (
                  <tr key={p.player_id} className="clickable" onClick={() => nav(`/player/${p.player_id}`)}>
                    <td><span className="rank-badge">{i + 1}</span></td>
                    <td>{p.name}</td>
                    <td className="muted">{p.team}</td>
                    <td className="num">{p.games}</td>
                    <td className="num" style={{ fontWeight: 800 }}>{p.avg}</td>
                  </tr>
                ))}
                {leaders.data?.length === 0 && <tr><td colSpan={5} className="muted">Sin datos de detalle todavía</td></tr>}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
