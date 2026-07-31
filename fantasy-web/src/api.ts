// Cliente de la API del fantasy. En local usa el proxy de Vite (/api). En producción,
// define VITE_API_BASE con la URL del backend al construir.
const ROOT = (import.meta as any).env?.VITE_API_BASE?.replace(/\/$/, "") ?? "";

let token: string | null = localStorage.getItem("pf_token");
export const getToken = () => token;
export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("pf_token", t);
  else localStorage.removeItem("pf_token");
}

function headers(json = false) {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}
async function msg(r: Response) {
  try { return (await r.json()).detail || `Error ${r.status}`; } catch { return `Error ${r.status}`; }
}
async function get<T = any>(p: string): Promise<T> {
  const r = await fetch(`${ROOT}/api${p}`, { headers: headers() });
  if (!r.ok) throw new Error(await msg(r));
  return r.json();
}
async function post<T = any>(p: string, body?: any): Promise<T> {
  const r = await fetch(`${ROOT}/api${p}`, {
    method: "POST", headers: headers(true), body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(await msg(r));
  return r.json();
}

export const api = {
  login: (email: string, password: string) => post("/auth/login", { email, password }),
  signup: (email: string, password: string, name?: string) => post("/auth/signup", { email, password, name }),
  me: () => get("/auth/me"),

  competitions: () => get<{ competitions: { competition: string; grupos: string[] }[] }>("/fantasy/competitions"),
  leagues: () => get<any[]>("/fantasy/leagues"),
  create: (b: any) => post("/fantasy/leagues", b),
  join: (join_code: string, manager_name: string) => post("/fantasy/leagues/join", { join_code, manager_name }),

  league: (id: number) => get(`/fantasy/leagues/${id}`),
  market: (id: number) => get(`/fantasy/leagues/${id}/market`),
  bid: (id: number, listing_id: number, amount: number) => post(`/fantasy/leagues/${id}/bid`, { listing_id, amount }),
  cancelBid: (id: number, listing_id: number) => post(`/fantasy/leagues/${id}/bid/cancel`, { listing_id }),
  closeMarket: (id: number) => post(`/fantasy/leagues/${id}/market/close`),
  openMarket: (id: number) => post(`/fantasy/leagues/${id}/market/open`),
  sell: (id: number, player_id: number) => post(`/fantasy/leagues/${id}/sell`, { player_id }),
  lineup: (id: number, starter_ids: number[]) => post(`/fantasy/leagues/${id}/lineup`, { starter_ids }),
  advance: (id: number) => post(`/fantasy/leagues/${id}/advance`),
  feed: (id: number) => get<any[]>(`/fantasy/leagues/${id}/feed`),
};

export const photo = (c: string | null | undefined) =>
  c ? `https://imagenes.feb.es/foto.aspx?c=${c}` : "";
export const shortName = (n: string) => (n?.includes(",") ? n.split(",")[0] : n ?? "").trim();
export const money = (v: number) => `${v} M€`;
