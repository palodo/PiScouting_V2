import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { IsoTrophy } from "../components/Iso";

function CreateLeague() {
  const nav = useNavigate();
  const meta = useAsync(() => api.fantasyCompetitions(), []);
  const [name, setName] = useState("");
  const [manager, setManager] = useState("");
  const [competition, setCompetition] = useState("");
  const [grupo, setGrupo] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const comps = meta.data?.competitions ?? [];
  const grupos = comps.find((c) => c.competition === competition)?.grupos ?? [];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const lg = await api.fantasyCreate({
        name, manager_name: manager, competition,
        grupo: grupo || (grupos.length ? grupos[0] : null),
      });
      nav(`/fantasy/${lg.id}`);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <form className="fa-panel" onSubmit={submit}>
      <h3 style={{ marginTop: 0 }}>Crear una liga</h3>
      <label className="field"><span>Nombre de la liga</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="La liga del grupo" required /></label>
      <label className="field"><span>Tu nombre de mánager</span>
        <input value={manager} onChange={(e) => setManager(e.target.value)} placeholder="Pau" /></label>
      <label className="field"><span>Conferencia (competición)</span>
        <select value={competition} onChange={(e) => { setCompetition(e.target.value); setGrupo(""); }} required>
          <option value="" disabled>Elige competición…</option>
          {comps.map((c) => <option key={c.competition} value={c.competition}>{c.competition}</option>)}
        </select></label>
      {grupos.length > 1 && (
        <label className="field"><span>Grupo</span>
          <select value={grupo} onChange={(e) => setGrupo(e.target.value)} required>
            <option value="" disabled>Elige grupo…</option>
            {grupos.map((g) => <option key={g} value={g}>{g}</option>)}
          </select></label>
      )}
      {err && <div className="error-box">{err}</div>}
      <button className="fa-btn block" disabled={busy || !competition}>{busy ? "Creando…" : "Crear liga"}</button>
      <p className="muted" style={{ fontSize: 12, margin: "12px 0 0" }}>
        Modo repetición: los precios arrancan con lo que va de temporada y la liga avanza jornada a jornada.
        ⚠️ 3ª FEB puede incluir menores de edad: úsala solo en privado, no publiques la app así.
      </p>
    </form>
  );
}

function JoinLeague() {
  const nav = useNavigate();
  const [code, setCode] = useState("");
  const [manager, setManager] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const lg = await api.fantasyJoin(code.trim().toUpperCase(), manager);
      nav(`/fantasy/${lg.id}`);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <form className="fa-panel" onSubmit={submit}>
      <h3 style={{ marginTop: 0 }}>Unirse con código</h3>
      <label className="field"><span>Código de invitación</span>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Ej. CJHD7Q"
          style={{ textTransform: "uppercase", letterSpacing: "0.14em", fontWeight: 800 }} required /></label>
      <label className="field"><span>Tu nombre de mánager</span>
        <input value={manager} onChange={(e) => setManager(e.target.value)} placeholder="Pau" /></label>
      {err && <div className="error-box">{err}</div>}
      <button className="fa-btn ghost block" disabled={busy}>{busy ? "…" : "Unirme a la liga"}</button>
    </form>
  );
}

export default function Fantasy() {
  const nav = useNavigate();
  const leagues = useAsync<any[]>(() => api.fantasyLeagues(), []);

  return (
    <div className="fantasy-app">
      <div className="fa-col">
        <div className="fa-home-top">
          <button className="fa-back" onClick={() => nav("/")}>‹ Volver al scouting</button>
        </div>
        <div className="fa-hero">
          <div className="fa-chip">🏆 FANTASY FEB</div>
          <div style={{ margin: "10px 0" }}><IsoTrophy size={168} /></div>
          <h1>Tu liga fantasy</h1>
          <p>Ficha jugadores de tu conferencia con presupuesto, alinea a tus 5 titulares
             y compite jornada a jornada. Los precios suben y bajan con la forma.</p>
        </div>

        {leagues.data && leagues.data.length > 0 && (
          <>
            <div className="fa-sec-title">Mis ligas</div>
            {leagues.data.map((l) => (
              <button key={l.id} className="fa-league" onClick={() => nav(`/fantasy/${l.id}`)}>
                <div className="fa-league-top">
                  <b>{l.name}</b>
                  <span className="fa-chip" style={{ fontSize: 10, padding: "4px 9px" }}>{l.competition}</span>
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{l.grupo}</div>
                <div className="fa-league-stats">
                  <div><b>{l.member_points}</b><span>tus puntos</span></div>
                  <div><b>{l.members}</b><span>mánagers</span></div>
                  <div><b>J{l.current_jornada}</b><span>de {l.max_jornada}</span></div>
                </div>
              </button>
            ))}
          </>
        )}

        <div className="fa-sec-title">Empezar</div>
        <CreateLeague />
        <JoinLeague />
      </div>
    </div>
  );
}
