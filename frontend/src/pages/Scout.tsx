import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import ShotChart from "../components/ShotChart";

function KeyPlayer({ p, nav }: { p: any; nav: any }) {
  const shots = useAsync<any>(() => api.shotsPlayer(p.player_id), [p.player_id]);
  const photo = p.photo_url || (p.feb_code ? `https://imagenes.feb.es/Foto.aspx?c=${p.feb_code}` : "");
  return (
    <div className="card keyplayer" onClick={() => nav(`/player/${p.player_id}`)}>
      <div className="kp-head">
        {photo && <img className="avatar" style={{ width: 54, height: 54 }} src={photo} onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
        <div>
          <div style={{ fontWeight: 800 }}>{p.name}</div>
          <div className="muted" style={{ fontSize: 12 }}>{p.min_avg} min · {p.games} PJ</div>
        </div>
      </div>
      <div className="kp-stats">
        <div><b>{p.ppg}</b><span>PTS</span></div>
        <div><b>{p.rpg}</b><span>REB</span></div>
        <div><b>{p.apg}</b><span>AST</span></div>
        <div><b>{p.ts_pct}%</b><span>TS</span></div>
        <div><b className={p.plus_minus_avg >= 0 ? "pos" : "neg"}>{p.plus_minus_avg >= 0 ? "+" : ""}{p.plus_minus_avg}</b><span>+/-</span></div>
      </div>
      {shots.data?.shots.length ? <ShotChart shots={shots.data.shots} height={260} /> : null}
    </div>
  );
}

export default function Scout() {
  const { id } = useParams();
  const tid = Number(id);
  const nav = useNavigate();
  const [reloadKey, setReloadKey] = useState(0);
  const [preparing, setPreparing] = useState(false);
  const rep = useAsync<any>(() => api.scout(tid), [tid, reloadKey]);
  const teamShots = useAsync<any>(() => api.shotsTeam(tid), [tid, reloadKey]);

  async function prepare() {
    setPreparing(true);
    try {
      await api.scoutPrepare(tid, 20);
      setReloadKey((k) => k + 1);
    } finally {
      setPreparing(false);
    }
  }

  if (rep.loading) return <div className="loader">Cargando scouting…</div>;
  if (!rep.data) return <div className="loader">No encontrado</div>;
  const d = rep.data;
  const t = d.team;
  const adv = d.advanced;

  return (
    <div>
      <div className="scout-head">
        <div>
          <div className="chip">SCOUTING</div>
          <h1 className="page-title" style={{ marginTop: 6 }}>
            {t.logo && <img className="team-logo" src={t.logo} style={{ width: 36, height: 36 }} />}
            {t.name}
          </h1>
          <p className="page-sub" style={{ margin: 0 }}>
            {t.competition}{t.grupo ? ` · ${t.grupo}` : ""} · {t.rank}º de {t.total_teams} ·
            {" "}{d.record.wins}-{d.record.losses} ({d.record.pts_for_avg}/{d.record.pts_against_avg})
          </p>
        </div>
        <button className="primary-btn" onClick={prepare} disabled={preparing}>
          {preparing ? "Analizando partidos…" : d.detail_ready ? "↻ Analizar más partidos" : "⚡ Preparar scouting completo"}
        </button>
      </div>

      {!d.detail_ready && !preparing && (
        <div className="card" style={{ borderColor: "var(--accent)" }}>
          <b>Análisis avanzado no preparado.</b>
          <p className="muted" style={{ marginBottom: 0 }}>
            Pulsa «Preparar scouting completo» para descargar el detalle de sus últimos partidos
            (boxscore + mapas de tiro) y calcular métricas avanzadas, jugadores clave y tiro.
          </p>
        </div>
      )}

      {preparing && <div className="card"><div className="loader">Descargando y analizando partidos del rival… (puede tardar ~30–60s)</div></div>}

      {d.detail_ready && (
        <>
          <h3>Perfil avanzado <span className="muted" style={{ fontSize: 12 }}>({adv.detail_games} partidos analizados)</span></h3>
          <div className="stat-grid" style={{ gridTemplateColumns: "repeat(6,1fr)", marginBottom: 18 }}>
            <div className="stat-box"><div className="v">{adv.off_rtg}</div><div className="k">OffRtg</div></div>
            <div className="stat-box"><div className="v">{adv.pace}</div><div className="k">Ritmo</div></div>
            <div className="stat-box"><div className="v">{adv.efg_pct}%</div><div className="k">eFG%</div></div>
            <div className="stat-box"><div className="v">{adv.ts_pct}%</div><div className="k">TS%</div></div>
            <div className="stat-box"><div className="v">{adv.ast_to}</div><div className="k">AST/TO</div></div>
            <div className="stat-box"><div className="v">{adv.three_rate}%</div><div className="k">% tiros de 3</div></div>
          </div>
        </>
      )}

      <div className="grid grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Clasificación del grupo</h3>
          <table>
            <thead><tr><th>#</th><th>Equipo</th><th className="num">V-D</th><th className="num">+/-</th></tr></thead>
            <tbody>
              {d.standings.map((s: any) => (
                <tr key={s.team_id} className={"clickable" + (s.team_id === tid ? " highlight" : "")}
                    onClick={() => nav(`/scout/${s.team_id}`)}>
                  <td><span className="rank-badge">{s.rank}</span></td>
                  <td>{s.name}</td>
                  <td className="num wl"><span className="w">{s.wins}</span>-<span className="l">{s.losses}</span></td>
                  <td className={"num " + (s.diff_avg >= 0 ? "pos" : "neg")}>{s.diff_avg >= 0 ? "+" : ""}{s.diff_avg}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Mapa de tiro del equipo</h3>
          {teamShots.data?.shots.length ? <ShotChart shots={teamShots.data.shots} /> :
            <div className="loader">Prepara el scouting para ver el mapa de tiro.</div>}
        </div>
      </div>

      {d.detail_ready && d.key_players.length > 0 && (
        <>
          <h3>Jugadores clave</h3>
          <div className="grid grid-3">
            {d.key_players.map((p: any) => <KeyPlayer key={p.player_id} p={p} nav={nav} />)}
          </div>
        </>
      )}

      {d.roster.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Plantilla</h3>
          <table>
            <thead>
              <tr>
                <th>Jugador</th><th className="num">PJ</th><th className="num">MIN</th><th className="num">PTS</th>
                <th className="num">REB</th><th className="num">AST</th><th className="num">T3/PJ</th>
                <th className="num">TS%</th><th className="num">VAL</th><th className="num">+/-</th>
              </tr>
            </thead>
            <tbody>
              {d.roster.map((p: any) => (
                <tr key={p.player_id} className="clickable" onClick={() => nav(`/player/${p.player_id}`)}>
                  <td>{p.name}</td><td className="num">{p.games}</td><td className="num">{p.min_avg}</td>
                  <td className="num" style={{ fontWeight: 700 }}>{p.ppg}</td>
                  <td className="num">{p.rpg}</td><td className="num">{p.apg}</td>
                  <td className="num">{p.fg3a_avg}</td><td className="num">{p.ts_pct}</td>
                  <td className="num">{p.val_avg}</td>
                  <td className={"num " + (p.plus_minus_avg >= 0 ? "pos" : "neg")}>{p.plus_minus_avg >= 0 ? "+" : ""}{p.plus_minus_avg}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
