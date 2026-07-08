import { useEffect, useState } from "react";
import { api, TeamRow } from "../api";
import { useAsync } from "../hooks";

function Bar({ label, a, b, better = "high" }: { label: string; a: number; b: number; better?: "high" | "low" }) {
  const max = Math.max(Math.abs(a), Math.abs(b), 0.001);
  const aWins = better === "high" ? a >= b : a <= b;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 5 }}>
        <b style={{ color: aWins ? "var(--made)" : "var(--text)" }}>{a}</b>
        <span className="muted">{label}</span>
        <b style={{ color: !aWins ? "var(--made)" : "var(--text)" }}>{b}</b>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <div style={{ flex: 1, display: "flex", justifyContent: "flex-end" }}>
          <div style={{ width: `${(Math.abs(a) / max) * 100}%`, height: 8, borderRadius: 4, background: aWins ? "var(--made)" : "var(--accent-2)" }} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ width: `${(Math.abs(b) / max) * 100}%`, height: 8, borderRadius: 4, background: !aWins ? "var(--made)" : "var(--accent)" }} />
        </div>
      </div>
    </div>
  );
}

export default function ComparePage() {
  const meta = useAsync(() => api.competitions(), []);
  const [competition, setCompetition] = useState("");
  const [a, setA] = useState<number | "">("");
  const [b, setB] = useState<number | "">("");

  useEffect(() => {
    if (meta.data && !competition && meta.data.competitions.length)
      setCompetition(meta.data.competitions[0].competition);
  }, [meta.data]);

  const teams = useAsync<TeamRow[]>(
    () => (competition ? api.teams(competition) : Promise.resolve([])),
    [competition]
  );
  useEffect(() => {
    if (teams.data && teams.data.length >= 2) {
      setA(teams.data[0].team_id);
      setB(teams.data[1].team_id);
    }
  }, [teams.data]);

  const cmp = useAsync<any[]>(
    () => (a !== "" && b !== "" ? api.compareTeams([Number(a), Number(b)]) : Promise.resolve([])),
    [a, b]
  );

  const [A, B] = cmp.data ?? [];

  return (
    <div>
      <h1 className="page-title">Comparar equipos</h1>
      <p className="page-sub">Enfrenta las medias de dos equipos</p>

      <div className="toolbar">
        <select value={competition} onChange={(e) => setCompetition(e.target.value)}>
          {meta.data?.competitions.map((c) => <option key={c.competition}>{c.competition}</option>)}
        </select>
        <select value={a} onChange={(e) => setA(Number(e.target.value))}>
          {teams.data?.map((t) => <option key={t.team_id} value={t.team_id}>{t.name}</option>)}
        </select>
        <span className="muted">vs</span>
        <select value={b} onChange={(e) => setB(Number(e.target.value))}>
          {teams.data?.map((t) => <option key={t.team_id} value={t.team_id}>{t.name}</option>)}
        </select>
      </div>

      {A && B && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
            <h3 style={{ margin: 0, color: "var(--accent-2)" }}>{A.name}</h3>
            <h3 style={{ margin: 0, color: "var(--accent)" }}>{B.name}</h3>
          </div>
          <Bar label="Victorias" a={A.record.wins} b={B.record.wins} />
          <Bar label="Puntos a favor" a={A.record.pts_for_avg} b={B.record.pts_for_avg} />
          <Bar label="Puntos en contra" a={A.record.pts_against_avg} b={B.record.pts_against_avg} better="low" />
          <Bar label="Diferencial" a={A.record.diff_avg} b={B.record.diff_avg} />
          <Bar label="T2%" a={A.shooting.fg2_pct} b={B.shooting.fg2_pct} />
          <Bar label="T3%" a={A.shooting.fg3_pct} b={B.shooting.fg3_pct} />
          <Bar label="TL%" a={A.shooting.ft_pct} b={B.shooting.ft_pct} />
          <Bar label="Asistencias" a={A.shooting.assists} b={B.shooting.assists} />
          <Bar label="Pérdidas" a={A.shooting.turnovers} b={B.shooting.turnovers} better="low" />
        </div>
      )}
    </div>
  );
}
