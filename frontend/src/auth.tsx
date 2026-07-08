import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api, setToken, getToken, AuthUser } from "./api";

interface AuthCtx {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, name?: string, teamId?: number) => Promise<void>;
  setTeam: (teamId: number) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>(null as any);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (getToken()) {
      api.me().then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  async function login(email: string, password: string) {
    const { token, user } = await api.login(email, password);
    setToken(token);
    setUser(user);
  }
  async function signup(email: string, password: string, name?: string, teamId?: number) {
    const { token, user } = await api.signup(email, password, name, teamId);
    setToken(token);
    setUser(user);
  }
  async function setTeam(teamId: number) {
    const u = await api.setMyTeam(teamId);
    setUser(u);
  }
  function logout() {
    setToken(null);
    setUser(null);
  }

  return (
    <Ctx.Provider value={{ user, loading, login, signup, setTeam, logout }}>
      {children}
    </Ctx.Provider>
  );
}
