import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";

// Si quieres forzar una URL concreta, ponla aquí (p.ej. "http://192.168.1.50:8000/api").
// Si se deja vacío, la app detecta automáticamente la IP del PC que sirve la app (Metro) y
// usa el puerto 8000 del backend. Así funciona en el móvil sin tocar nada, siempre que:
//   1) el móvil y el PC estén en la MISMA WiFi, y
//   2) el backend se arranque con  --host 0.0.0.0  (accesible desde la red).
const OVERRIDE = "";

function resolveBase(): string {
  if (OVERRIDE) return OVERRIDE;
  const hostUri =
    (Constants as any).expoConfig?.hostUri ||
    (Constants as any).expoGoConfig?.debuggerHost ||
    (Constants as any).manifest?.debuggerHost ||
    "";
  const host = hostUri.split(":")[0] || "127.0.0.1";
  return `http://${host}:8000/api`;
}

export const API_BASE = resolveBase();

let token: string | null = null;
export async function loadToken() { token = await AsyncStorage.getItem("pi_token"); return token; }
export async function setToken(t: string | null) {
  token = t;
  if (t) await AsyncStorage.setItem("pi_token", t);
  else await AsyncStorage.removeItem("pi_token");
}
export function hasToken() { return !!token; }

function headers(json = false): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}
async function err(r: Response) {
  try { return (await r.json()).detail || `${r.status}`; } catch { return `${r.status}`; }
}
async function get<T = any>(p: string): Promise<T> {
  const r = await fetch(API_BASE + p, { headers: headers() });
  if (!r.ok) throw new Error(await err(r));
  return r.json();
}
async function post<T = any>(p: string, body?: any): Promise<T> {
  const r = await fetch(API_BASE + p, { method: "POST", headers: headers(true), body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(await err(r));
  return r.json();
}

export const api = {
  login: (email: string, password: string) => post("/auth/login", { email, password }),
  signup: (email: string, password: string) => post("/auth/signup", { email, password }),
  fantasyCompetitions: () => get("/fantasy/competitions"),
  leagues: () => get<any[]>("/fantasy/leagues"),
  create: (b: any) => post("/fantasy/leagues", b),
  join: (join_code: string, manager_name: string) => post("/fantasy/leagues/join", { join_code, manager_name }),
  league: (id: number) => get(`/fantasy/leagues/${id}`),
  market: (id: number) => get(`/fantasy/leagues/${id}/market`),
  buy: (id: number, player_id: number) => post(`/fantasy/leagues/${id}/buy`, { player_id }),
  sell: (id: number, player_id: number) => post(`/fantasy/leagues/${id}/sell`, { player_id }),
  lineup: (id: number, starter_ids: number[]) => post(`/fantasy/leagues/${id}/lineup`, { starter_ids }),
  advance: (id: number) => post(`/fantasy/leagues/${id}/advance`),
};

export const photo = (c: string | null) => (c ? `https://imagenes.feb.es/foto.aspx?c=${c}` : "");
export const firstName = (n: string) => (n.includes(",") ? n.split(",")[0] : n).trim();
