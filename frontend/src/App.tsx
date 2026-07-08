import { useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import MyTeam from "./pages/MyTeam";
import Scout from "./pages/Scout";
import Rankings from "./pages/Rankings";
import TeamPage from "./pages/TeamPage";
import PlayerPage from "./pages/PlayerPage";
import MatchPage from "./pages/MatchPage";
import ComparePage from "./pages/ComparePage";
import TeamPicker from "./components/TeamPicker";

function Sidebar() {
  const { user, logout } = useAuth();
  return (
    <aside className="sidebar">
      <div className="brand">Pi<span>Scouting</span></div>
      <div className="brand-sub">FEB · Análisis de baloncesto</div>
      {user?.team && (
        <div className="my-team-chip">
          {user.team.logo && <img src={user.team.logo} />}
          <div>
            <div style={{ fontWeight: 700, fontSize: 13 }}>{user.team.name}</div>
            <div className="muted" style={{ fontSize: 11 }}>{user.team.competition}</div>
          </div>
        </div>
      )}
      <nav className="nav">
        <NavLink to="/" end>🏠 Mi equipo</NavLink>
        <NavLink to="/rankings">📊 Rankings</NavLink>
        <NavLink to="/compare">⚔️ Comparar</NavLink>
        <NavLink to="/settings">⚙️ Ajustes</NavLink>
      </nav>
      <div className="sidebar-foot">
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>{user?.email}</div>
        <button onClick={logout}>Cerrar sesión</button>
      </div>
    </aside>
  );
}

function ChooseTeam() {
  const { setTeam } = useAuth();
  const [teamId, setTeamId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h2 style={{ marginTop: 0 }}>Elige tu equipo</h2>
        <p className="muted">Verás tu equipo, su calendario y el scouting de tus rivales.</p>
        <TeamPicker value={teamId} onChange={setTeamId} />
        <button className="primary-btn" style={{ marginTop: 16 }} disabled={!teamId || busy}
          onClick={async () => { setBusy(true); try { await setTeam(teamId!); } finally { setBusy(false); } }}>
          Continuar
        </button>
      </div>
    </div>
  );
}

function Settings() {
  const { user, setTeam } = useAuth();
  const [teamId, setTeamId] = useState<number | null>(user?.team?.team_id ?? null);
  const [saved, setSaved] = useState(false);
  return (
    <div style={{ maxWidth: 480 }}>
      <h1 className="page-title">Ajustes</h1>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Cambiar mi equipo</h3>
        <TeamPicker value={teamId} onChange={(id) => { setTeamId(id); setSaved(false); }} />
        <button className="primary-btn" style={{ marginTop: 14 }} disabled={!teamId}
          onClick={async () => { await setTeam(teamId!); setSaved(true); }}>Guardar</button>
        {saved && <span className="pos" style={{ marginLeft: 12 }}>✓ Guardado</span>}
      </div>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="loader" style={{ marginTop: 80 }}>Cargando…</div>;
  if (!user) return <Login />;
  if (!user.team) return <ChooseTeam />;

  return (
    <div className="layout">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<MyTeam />} />
          <Route path="/rankings" element={<Rankings />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/scout/:id" element={<Scout />} />
          <Route path="/team/:id" element={<TeamPage />} />
          <Route path="/player/:id" element={<PlayerPage />} />
          <Route path="/match/:id" element={<MatchPage />} />
        </Routes>
      </main>
    </div>
  );
}
