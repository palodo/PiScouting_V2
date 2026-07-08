import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import ShotChart from "../components/ShotChart";

function Boxscore({ side, nav }: { side: any; nav: any }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>
        {side.logo && <img className="team-logo" src={side.logo} />}{side.name} · {side.score}
      </h3>
      <table>
        <thead>
          <tr><th>Jugador</th><th className="num">MIN</th><th className="num">PTS</th><th className="num">T2</th><th className="num">T3</th><th className="num">REB</th><th className="num">AST</th><th className="num">VAL</th><th className="num">+/-</th></tr>
        </thead>
        <tbody>
          {side.boxscore.map((b: any) => (
            <tr key={b.player_id} className="clickable" onClick={() => nav(`/player/${b.player_id}`)}>
              <td>{b.starter ? "▶ " : ""}{b.name}</td>
              <td className="num">{b.min}</td>
              <td className="num" style={{ fontWeight: 700 }}>{b.pts}</td>
              <td className="num">{b.t2}</td>
              <td className="num">{b.t3}</td>
              <td className="num">{b.treb}</td>
              <td className="num">{b.ast}</td>
              <td className="num">{b.val}</td>
              <td className={"num " + (b.plus_minus >= 0 ? "pos" : "neg")}>{b.plus_minus >= 0 ? "+" : ""}{b.plus_minus}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MatchPage() {
  const { id } = useParams();
  const mid = Number(id);
  const nav = useNavigate();
  const match = useAsync<any>(() => api.match(mid), [mid]);
  const [side, setSide] = useState<"home" | "away">("home");
  const teamId = match.data ? match.data[side].team_id : undefined;
  const shots = useAsync<any>(() => (teamId ? api.shotsMatch(mid, teamId) : Promise.resolve(null)), [mid, teamId]);

  if (match.loading) return <div className="loader">Cargando partido…</div>;
  if (!match.data) return <div className="loader">No encontrado</div>;
  const m = match.data;
  const homeWin = (m.home.score ?? 0) > (m.away.score ?? 0);

  return (
    <div>
      <Link to="#" onClick={() => nav(-1)} className="muted">← Volver</Link>
      <p className="page-sub" style={{ marginTop: 8 }}>{m.competition} · {m.jornada} · {m.date}</p>
      <div className="scoreline">
        <div className="t"><div className="n">{m.home.name}</div></div>
        <div className={"sc " + (homeWin ? "win" : "")}>{m.home.score}</div>
        <div className="muted">-</div>
        <div className={"sc " + (!homeWin ? "win" : "")}>{m.away.score}</div>
        <div className="t"><div className="n">{m.away.name}</div></div>
      </div>

      {m.quarters?.length > 0 && (
        <div className="card">
          <table>
            <thead>
              <tr><th>Parciales</th>{m.quarters.map((q: any) => <th key={q.n} className="num">Q{q.n}</th>)}</tr>
            </thead>
            <tbody>
              <tr><td>{m.home.name}</td>{m.quarters.map((q: any) => <td key={q.n} className="num">{q.home}</td>)}</tr>
              <tr><td>{m.away.name}</td>{m.quarters.map((q: any) => <td key={q.n} className="num">{q.away}</td>)}</tr>
            </tbody>
          </table>
          {m.venue && <p className="muted" style={{ marginBottom: 0 }}>🏟 {m.venue}{m.referees ? ` · 🧑‍⚖️ ${m.referees}` : ""}</p>}
        </div>
      )}

      <div className="card">
        <div className="tabs">
          <button className={side === "home" ? "active" : ""} onClick={() => setSide("home")}>{m.home.name}</button>
          <button className={side === "away" ? "active" : ""} onClick={() => setSide("away")}>{m.away.name}</button>
        </div>
        <h3 style={{ marginTop: 0 }}>Mapa de tiro · {m[side].name}</h3>
        {shots.loading ? <div className="loader">Cargando…</div> :
          (shots.data?.shots.length ? <ShotChart shots={shots.data.shots} animate /> :
            <div className="loader">Sin tiros para este partido</div>)}
      </div>

      <div className="grid grid-2">
        <Boxscore side={m.home} nav={nav} />
        <Boxscore side={m.away} nav={nav} />
      </div>
    </div>
  );
}
