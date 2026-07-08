import { useParams, useNavigate, Link } from "react-router-dom";
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

export default function PlayerPage() {
  const { id } = useParams();
  const pid = Number(id);
  const nav = useNavigate();
  const player = useAsync<any>(() => api.player(pid), [pid]);
  const shots = useAsync<any>(() => api.shotsPlayer(pid), [pid]);

  if (player.loading) return <div className="loader">Cargando jugador…</div>;
  if (!player.data) return <div className="loader">No encontrado</div>;
  const p = player.data;
  const a = p.averages;
  const photo = p.photo_url || (p.feb_code ? `https://imagenes.feb.es/Foto.aspx?c=${p.feb_code}` : "");

  return (
    <div>
      <Link to="#" onClick={() => nav(-1)} className="muted">← Volver</Link>
      <div className="player-head" style={{ marginTop: 10 }}>
        {photo && <img className="avatar" src={photo} onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>{p.name}</h1>
          <p className="page-sub" style={{ margin: "4px 0 0" }}>{p.games} partidos con detalle</p>
        </div>
      </div>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <StatBox k="Puntos" v={a.ppg} />
        <StatBox k="Valoración" v={a.val_avg} />
        <StatBox k="+/- medio" v={`${a.plus_minus_avg >= 0 ? "+" : ""}${a.plus_minus_avg}`} tone={a.plus_minus_avg >= 0 ? "pos" : "neg"} />
        <StatBox k="Minutos" v={a.min_avg} />
        <StatBox k="Rebotes" v={a.rpg} />
        <StatBox k="Asistencias" v={a.apg} />
        <StatBox k="T2 / T3 / TL %" v={`${a.fg2_pct}/${a.fg3_pct}/${a.ft_pct}`} />
        <StatBox k="Robos / Pérdidas" v={`${a.spg} / ${a.topg}`} />
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Mapa de tiro animado</h3>
          {shots.loading ? <div className="loader">Cargando…</div> :
            (shots.data?.shots.length ? <ShotChart shots={shots.data.shots} animate /> :
              <div className="loader">Sin tiros registrados</div>)}
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Registro de partidos</h3>
          <table>
            <thead>
              <tr><th>Fecha</th><th className="num">MIN</th><th className="num">PTS</th><th className="num">REB</th><th className="num">AST</th><th className="num">VAL</th><th className="num">+/-</th></tr>
            </thead>
            <tbody>
              {p.gamelog.map((g: any) => (
                <tr key={g.match_id} className="clickable" onClick={() => nav(`/match/${g.match_id}`)}>
                  <td>{g.date ?? g.jornada}</td>
                  <td className="num">{g.min}</td>
                  <td className="num" style={{ fontWeight: 700 }}>{g.pts}</td>
                  <td className="num">{g.treb}</td>
                  <td className="num">{g.ast}</td>
                  <td className="num">{g.val}</td>
                  <td className={"num " + (g.plus_minus >= 0 ? "pos" : "neg")}>{g.plus_minus >= 0 ? "+" : ""}{g.plus_minus}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
