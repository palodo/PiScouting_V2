import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";

function photoOf(p: any) {
  return p.photo_url || (p.feb_code ? `https://imagenes.feb.es/Foto.aspx?c=${p.feb_code}` : "");
}

function Leaderboard({ title, icon, rows, stat, unit, nav }: any) {
  return (
    <div className="card lb-card">
      <h3 style={{ marginTop: 0 }}>{icon} {title}</h3>
      <div className="lb-list">
        {rows.map((p: any, i: number) => (
          <div key={p.player_id} className="lb-row" onClick={() => nav(`/player/${p.player_id}`)}>
            <span className={"lb-pos" + (i < 3 ? " medal m" + (i + 1) : "")}>{i + 1}</span>
            <img className="lb-photo" src={photoOf(p)} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
            <div className="lb-info">
              <div className="lb-name">{p.name}</div>
              <div className="lb-team">{p.team}</div>
            </div>
            <span className="lb-val">{p[stat]}<small>{unit}</small></span>
          </div>
        ))}
        {rows.length === 0 && <div className="muted" style={{ padding: 10 }}>Sin datos con detalle.</div>}
      </div>
    </div>
  );
}

export default function JornadaPage() {
  const nav = useNavigate();
  const meta = useAsync(() => api.competitions(), []);
  const [competition, setCompetition] = useState("");
  const [grupo, setGrupo] = useState("");
  const [jornada, setJornada] = useState<number | null>(null);

  useEffect(() => {
    if (meta.data && !competition && meta.data.competitions.length)
      setCompetition(meta.data.competitions[0].competition);
  }, [meta.data]);

  const grupos = meta.data?.competitions.find((c) => c.competition === competition)?.grupos ?? [];
  const jornadas = useAsync<number[]>(
    () => (competition ? api.jornadaList(competition, grupo || undefined) : Promise.resolve([])),
    [competition, grupo]
  );
  useEffect(() => {
    if (jornadas.data && jornadas.data.length) setJornada(jornadas.data[jornadas.data.length - 1]);
  }, [jornadas.data]);

  const sum = useAsync<any>(
    () => (competition && jornada ? api.jornadaSummary(competition, jornada, grupo || undefined) : Promise.resolve(null)),
    [competition, grupo, jornada]
  );

  const d = sum.data;
  const mvp = d?.mvp;

  return (
    <div>
      <h1 className="page-title">Resumen de la jornada</h1>
      <p className="page-sub">Resultados y mejores actuaciones · Temporada 2025/26</p>

      <div className="toolbar">
        <select value={competition} onChange={(e) => { setCompetition(e.target.value); setGrupo(""); }}>
          {meta.data?.competitions.map((c) => <option key={c.competition} value={c.competition}>{c.competition}</option>)}
        </select>
        {grupos.length > 1 && (
          <select value={grupo} onChange={(e) => setGrupo(e.target.value)}>
            <option value="">Elige grupo…</option>
            {grupos.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        )}
        <div className="jornada-nav">
          <button disabled={!jornada || jornada <= (jornadas.data?.[0] ?? 1)}
            onClick={() => setJornada((j) => (j ? j - 1 : j))}>‹</button>
          <select value={jornada ?? ""} onChange={(e) => setJornada(Number(e.target.value))}>
            {jornadas.data?.map((j) => <option key={j} value={j}>Jornada {j}</option>)}
          </select>
          <button disabled={!jornada || jornada >= (jornadas.data?.[jornadas.data.length - 1] ?? 99)}
            onClick={() => setJornada((j) => (j ? j + 1 : j))}>›</button>
        </div>
      </div>

      {sum.loading && <div className="loader">Cargando jornada…</div>}
      {d && (grupos.length <= 1 || grupo) && (
        <>
          {mvp && (
            <div className="card mvp-card">
              <div className="mvp-badge">★ MVP DE LA JORNADA</div>
              <img className="mvp-photo" src={photoOf(mvp)} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
              <div className="mvp-info">
                <div className="mvp-name" onClick={() => nav(`/player/${mvp.player_id}`)}>{mvp.name}</div>
                <div className="mvp-team">{mvp.team_logo && <img src={mvp.team_logo} />}{mvp.team}</div>
                <div className="mvp-stats">
                  <div><b>{mvp.val}</b><span>VALORACIÓN</span></div>
                  <div><b>{mvp.pts}</b><span>PUNTOS</span></div>
                  <div><b>{mvp.treb}</b><span>REBOTES</span></div>
                  <div><b>{mvp.ast}</b><span>ASIST.</span></div>
                  <div><b>{mvp.t3m}</b><span>TRIPLES</span></div>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-3">
            <Leaderboard title="Más puntos" icon="🏀" rows={d.top_pts} stat="pts" unit="" nav={nav} />
            <Leaderboard title="Mejor valoración" icon="⭐" rows={d.top_val} stat="val" unit="" nav={nav} />
            <Leaderboard title="Más triples" icon="🎯" rows={d.top_t3} stat="t3m" unit="" nav={nav} />
            <Leaderboard title="Más rebotes" icon="💪" rows={d.top_treb} stat="treb" unit="" nav={nav} />
            <Leaderboard title="Más asistencias" icon="🤝" rows={d.top_ast} stat="ast" unit="" nav={nav} />
            <div className="card">
              <h3 style={{ marginTop: 0 }}>📋 Resultados <span className="muted" style={{ fontSize: 12 }}>({d.played}/{d.num_matches})</span></h3>
              <div className="jr-results">
                {d.results.map((r: any) => (
                  <div key={r.match_id} className="jr-match" onClick={() => r.played && nav(`/match/${r.match_id}`)}>
                    <span className={"jr-team" + (r.home_win ? " w" : "")}>{r.home}</span>
                    <span className="jr-score">{r.played ? `${r.home_score}-${r.away_score}` : "—"}</span>
                    <span className={"jr-team a" + (r.played && !r.home_win ? " w" : "")}>{r.away}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
      {d && grupos.length > 1 && !grupo && (
        <div className="card muted">Elige un grupo para ver el resumen de la jornada.</div>
      )}
    </div>
  );
}
