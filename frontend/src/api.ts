// Cliente ligero de la API de PiScouting.

export const DEFAULT_SEASON = "2025";

let authToken: string | null = localStorage.getItem("pi_token");
export function setToken(t: string | null) {
  authToken = t;
  if (t) localStorage.setItem("pi_token", t);
  else localStorage.removeItem("pi_token");
}
export function getToken() {
  return authToken;
}

function headers(extra?: Record<string, string>) {
  const h: Record<string, string> = { ...(extra ?? {}) };
  if (authToken) h["Authorization"] = `Bearer ${authToken}`;
  return h;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { headers: headers() });
  if (!res.ok) throw new Error(await errMsg(res));
  return res.json() as Promise<T>;
}

async function send<T>(method: string, path: string, body?: any): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: headers({ "Content-Type": "application/json" }),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(await errMsg(res));
  return res.json() as Promise<T>;
}

async function errMsg(res: Response): Promise<string> {
  try {
    const d = await res.json();
    return d.detail || `${res.status}`;
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export interface AuthUser {
  id: number;
  email: string;
  name: string | null;
  team: { team_id: number; name: string; logo: string | null; competition: string; grupo: string | null } | null;
}

export interface CompetitionMeta {
  competition: string;
  teams: number;
  grupos: string[];
}
export interface TeamRow {
  team_id: number;
  name: string;
  logo: string | null;
  grupo: string | null;
  rank?: number;
  games: number;
  wins: number;
  losses: number;
  win_pct: number;
  pts_for_avg: number;
  pts_against_avg: number;
  diff_avg: number;
}
export interface LeaderRow {
  player_id: number;
  name: string;
  photo_url: string | null;
  team_id: number;
  team: string;
  games: number;
  stat: string;
  avg: number;
  total: number;
}
export interface Shot {
  hx: number;
  hy: number;
  made: boolean;
  quarter: number | null;
  clock: string | null;
  t: number | null;
  player_id: number | null;
  is_home: boolean;
}
export interface ShotResponse {
  summary: { attempts: number; made: number; pct: number };
  shots: Shot[];
}

export const api = {
  health: () => get<{ status: string; counts: Record<string, number> }>("/health"),
  competitions: (season = DEFAULT_SEASON) =>
    get<{ season: string; competitions: CompetitionMeta[] }>(
      `/meta/competitions?season=${season}`
    ),
  teams: (competition?: string, grupo?: string, season = DEFAULT_SEASON) => {
    const p = new URLSearchParams({ season });
    if (competition) p.set("competition", competition);
    if (grupo) p.set("grupo", grupo);
    return get<TeamRow[]>(`/teams?${p}`);
  },
  team: (id: number) => get<any>(`/teams/${id}`),
  player: (id: number) => get<any>(`/players/${id}`),
  match: (id: number) => get<any>(`/matches/${id}`),
  rankingsTeams: (competition: string, grupo?: string, season = DEFAULT_SEASON) => {
    const p = new URLSearchParams({ competition, season });
    if (grupo) p.set("grupo", grupo);
    return get<TeamRow[]>(`/rankings/teams?${p}`);
  },
  rankingsPlayers: (competition: string, stat = "pts", limit = 25, season = DEFAULT_SEASON) =>
    get<LeaderRow[]>(
      `/rankings/players?competition=${encodeURIComponent(competition)}&stat=${stat}&limit=${limit}&season=${season}`
    ),
  compareTeams: (ids: number[]) => get<any[]>(`/compare/teams?ids=${ids.join(",")}`),
  shotsTeam: (id: number) => get<ShotResponse>(`/shots/team/${id}`),
  shotsPlayer: (id: number) => get<ShotResponse>(`/shots/player/${id}`),
  shotsMatch: (id: number, teamId?: number) =>
    get<ShotResponse>(`/shots/match/${id}${teamId ? `?team_id=${teamId}` : ""}`),

  // Auth
  signup: (email: string, password: string, name?: string, team_id?: number) =>
    send<{ token: string; user: AuthUser }>("POST", "/auth/signup", { email, password, name, team_id }),
  login: (email: string, password: string) =>
    send<{ token: string; user: AuthUser }>("POST", "/auth/login", { email, password }),
  me: () => get<AuthUser>("/auth/me"),
  setMyTeam: (team_id: number) => send<AuthUser>("PUT", "/auth/me/team", { team_id }),

  // Scouting
  dashboard: (simJornada?: number) =>
    get<any>(`/me/dashboard${simJornada != null ? `?sim_jornada=${simJornada}` : ""}`),
  schedule: (teamId: number) => get<any[]>(`/teams/${teamId}/schedule`),
  nextOpponent: (teamId: number) => get<any>(`/teams/${teamId}/next`),
  scout: (teamId: number) => get<any>(`/scout/${teamId}`),
  scoutPrepare: (teamId: number, limit = 20) => send<any>("POST", `/scout/${teamId}/prepare?limit=${limit}`),
};
