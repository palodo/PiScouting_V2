import { useEffect, useState } from "react";
import { api, TeamRow } from "../api";
import { useAsync } from "../hooks";

interface Props {
  value: number | null;
  onChange: (teamId: number | null) => void;
}

export default function TeamPicker({ value, onChange }: Props) {
  const meta = useAsync(() => api.competitions(), []);
  const [competition, setCompetition] = useState("");
  const [grupo, setGrupo] = useState("");

  useEffect(() => {
    if (meta.data && !competition && meta.data.competitions.length)
      setCompetition(meta.data.competitions[0].competition);
  }, [meta.data]);

  const grupos = meta.data?.competitions.find((c) => c.competition === competition)?.grupos ?? [];
  const teams = useAsync<TeamRow[]>(
    () => (competition ? api.teams(competition, grupo || undefined) : Promise.resolve([])),
    [competition, grupo]
  );

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <select value={competition} onChange={(e) => { setCompetition(e.target.value); setGrupo(""); onChange(null); }}>
        {meta.data?.competitions.map((c) => (
          <option key={c.competition} value={c.competition}>{c.competition}</option>
        ))}
      </select>
      {grupos.length > 1 && (
        <select value={grupo} onChange={(e) => { setGrupo(e.target.value); onChange(null); }}>
          <option value="">Elige grupo…</option>
          {grupos.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
      )}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">Elige tu equipo…</option>
        {teams.data?.map((t) => <option key={t.team_id} value={t.team_id}>{t.name}</option>)}
      </select>
    </div>
  );
}
