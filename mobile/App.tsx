import { useEffect, useState } from "react";
import {
  ActivityIndicator, Image, Pressable, ScrollView, StatusBar,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { api, firstName, hasToken, loadToken, photo, setToken } from "./src/api";
import { C } from "./src/theme";

export default function App() {
  const [booted, setBooted] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [leagueId, setLeagueId] = useState<number | null>(null);

  useEffect(() => { loadToken().then(() => { setAuthed(hasToken()); setBooted(true); }); }, []);

  if (!booted) return <View style={s.center}><ActivityIndicator color={C.orange} /></View>;
  if (!authed) return <Login onAuth={() => setAuthed(true)} />;
  if (leagueId) return <League id={leagueId} onBack={() => setLeagueId(null)} />;
  return <Leagues onOpen={setLeagueId} onLogout={async () => { await setToken(null); setAuthed(false); }} />;
}

/* ------------------------------------------------------------------ Login */
function Login({ onAuth }: { onAuth: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null); setBusy(true);
    try {
      const r = mode === "login" ? await api.login(email.trim(), pass) : await api.signup(email.trim(), pass);
      await setToken(r.token);
      onAuth();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <View style={[s.screen, s.center, { padding: 24 }]}>
      <StatusBar barStyle="light-content" />
      <Text style={s.logo}>Pi<Text style={{ color: C.orange }}>Fantasy</Text></Text>
      <Text style={[s.dim, { marginBottom: 26 }]}>Fantasy de baloncesto FEB</Text>
      <View style={s.segment}>
        {(["login", "signup"] as const).map((m) => (
          <Pressable key={m} onPress={() => setMode(m)} style={[s.segBtn, mode === m && s.segBtnOn]}>
            <Text style={[s.segTxt, mode === m && { color: "#14203a" }]}>{m === "login" ? "Entrar" : "Crear cuenta"}</Text>
          </Pressable>
        ))}
      </View>
      <TextInput style={s.input} placeholder="Email" placeholderTextColor={C.muted}
        autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <TextInput style={s.input} placeholder="Contraseña" placeholderTextColor={C.muted}
        secureTextEntry value={pass} onChangeText={setPass} />
      {err && <Text style={s.err}>{err}</Text>}
      <Pressable style={[s.btn, { marginTop: 6, width: 300 }]} disabled={busy} onPress={submit}>
        <Text style={s.btnTxt}>{busy ? "…" : mode === "login" ? "Entrar" : "Crear cuenta"}</Text>
      </Pressable>
    </View>
  );
}

/* ------------------------------------------------------------------ Leagues */
function Leagues({ onOpen, onLogout }: { onOpen: (id: number) => void; onLogout: () => void }) {
  const [leagues, setLeagues] = useState<any[] | null>(null);
  const [comps, setComps] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [manager, setManager] = useState("");
  const [comp, setComp] = useState("");
  const [grupo, setGrupo] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reload() { setLeagues(await api.leagues()); }
  useEffect(() => { reload(); api.fantasyCompetitions().then((d) => setComps(d.competitions)); }, []);
  const grupos = comps.find((c) => c.competition === comp)?.grupos ?? [];

  async function create() {
    setErr(null); setBusy(true);
    try {
      const lg = await api.create({ name, manager_name: manager, competition: comp, grupo: grupo || grupos[0] || null });
      onOpen(lg.id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function join() {
    setErr(null); setBusy(true);
    try { const lg = await api.join(code.trim().toUpperCase(), manager); onOpen(lg.id); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <ScrollView style={s.screen} contentContainerStyle={{ padding: 18, paddingTop: 48, paddingBottom: 60 }}>
      <StatusBar barStyle="light-content" />
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={s.logo}>Pi<Text style={{ color: C.orange }}>Fantasy</Text></Text>
        <Pressable onPress={onLogout}><Text style={s.dim}>Salir</Text></Pressable>
      </View>
      <Text style={[s.h1, { marginTop: 18 }]}>Tu liga fantasy</Text>
      <Text style={[s.dim, { marginBottom: 8 }]}>Ficha jugadores con presupuesto, alinea 5 titulares y compite jornada a jornada.</Text>

      {leagues && leagues.length > 0 && <>
        <Text style={s.section}>MIS LIGAS</Text>
        {leagues.map((l) => (
          <Pressable key={l.id} style={s.leagueCard} onPress={() => onOpen(l.id)}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={s.leagueName}>{l.name}</Text>
              <Text style={s.chip}>{l.competition}</Text>
            </View>
            <Text style={[s.dim, { fontSize: 12 }]}>{l.grupo}</Text>
            <View style={s.leagueStats}>
              {[[l.member_points, "tus puntos"], [l.members, "mánagers"], [`J${l.current_jornada}`, `de ${l.max_jornada}`]].map(([v, k], i) => (
                <View key={i} style={s.miniStat}><Text style={s.miniV}>{v}</Text><Text style={s.miniK}>{k}</Text></View>
              ))}
            </View>
          </Pressable>
        ))}
      </>}

      <Text style={s.section}>CREAR LIGA</Text>
      <View style={s.panel}>
        <TextInput style={s.input} placeholder="Nombre de la liga" placeholderTextColor={C.muted} value={name} onChangeText={setName} />
        <TextInput style={s.input} placeholder="Tu nombre de mánager" placeholderTextColor={C.muted} value={manager} onChangeText={setManager} />
        <Text style={s.label}>Conferencia</Text>
        <View style={s.chipRow}>
          {comps.map((c) => (
            <Pressable key={c.competition} onPress={() => { setComp(c.competition); setGrupo(""); }} style={[s.pick, comp === c.competition && s.pickOn]}>
              <Text style={[s.pickTxt, comp === c.competition && { color: "#14203a" }]}>{c.competition}</Text>
            </Pressable>
          ))}
        </View>
        {grupos.length > 1 && <>
          <Text style={s.label}>Grupo</Text>
          <View style={s.chipRow}>
            {grupos.map((g: string) => (
              <Pressable key={g} onPress={() => setGrupo(g)} style={[s.pick, grupo === g && s.pickOn]}>
                <Text style={[s.pickTxt, grupo === g && { color: "#14203a" }]}>{g.replace("Liga Regular ", "")}</Text>
              </Pressable>
            ))}
          </View>
        </>}
        {err && <Text style={s.err}>{err}</Text>}
        <Pressable style={[s.btn, (!comp || busy) && s.btnOff]} disabled={!comp || busy} onPress={create}>
          <Text style={s.btnTxt}>{busy ? "…" : "Crear liga"}</Text>
        </Pressable>
        <Text style={[s.dim, { fontSize: 11, marginTop: 10 }]}>⚠️ 3ª FEB puede incluir menores de edad: úsala solo en privado, no publiques la app así.</Text>
      </View>

      <Text style={s.section}>UNIRSE CON CÓDIGO</Text>
      <View style={s.panel}>
        <TextInput style={[s.input, { letterSpacing: 3, fontWeight: "800" }]} placeholder="CÓDIGO" placeholderTextColor={C.muted}
          autoCapitalize="characters" value={code} onChangeText={setCode} />
        <Pressable style={[s.btn, s.btnGhost]} disabled={busy} onPress={join}><Text style={[s.btnTxt, { color: "#fff" }]}>Unirme</Text></Pressable>
      </View>
    </ScrollView>
  );
}

/* ------------------------------------------------------------------ League */
const POS = [{ l: "50%", t: "78%" }, { l: "16%", t: "58%" }, { l: "84%", t: "58%" }, { l: "32%", t: "36%" }, { l: "66%", t: "24%" }];

function League({ id, onBack }: { id: number; onBack: () => void }) {
  const [tab, setTab] = useState<"equipo" | "mercado" | "liga">("equipo");
  const [data, setData] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [inited, setInited] = useState(false);

  async function load() { const d = await api.league(id); setData(d); return d; }
  async function loadMarket() { setMarket(await api.market(id)); }
  useEffect(() => {
    load().then((d) => {
      if (!inited) { setInited(true); if ((d.my_squad?.length ?? 0) === 0) { setTab("mercado"); loadMarket(); } }
    });
  }, []);
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 2000); return () => clearTimeout(t); }, [msg]);

  if (!data) return <View style={[s.screen, s.center]}><ActivityIndicator color={C.orange} /></View>;
  const lg = data.league;
  const squad = (data.my_squad as any[]) ?? [];
  const starters = squad.filter((p) => p.starter);
  const bench = squad.filter((p) => !p.starter);
  const done = lg.current_jornada >= lg.max_jornada;

  async function act(fn: () => Promise<any>, note?: string) {
    setBusy(true);
    try { await fn(); await load(); if (market) await loadMarket(); if (note) setMsg(note); }
    catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }
  function toggleStarter(pid: number, isStarter: boolean) {
    const ids = starters.map((p) => p.player_id);
    if (!isStarter && ids.length >= lg.lineup_size) { setMsg(`Máx. ${lg.lineup_size} titulares`); return; }
    act(() => api.lineup(id, isStarter ? ids.filter((x) => x !== pid) : [...ids, pid]));
  }

  return (
    <View style={s.screen}>
      <StatusBar barStyle="light-content" />
      <View style={s.topbar}>
        <Pressable onPress={onBack}><Text style={s.dim}>‹ Mis ligas</Text></Pressable>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
          <Text style={s.h1}>{lg.name}</Text>
          {data.is_owner && (
            <Pressable style={[s.btnSm, (busy || done) && s.btnOff]} disabled={busy || done}
              onPress={() => act(() => api.advance(id), done ? undefined : "¡Jornada puntuada!")}>
              <Text style={s.btnTxt}>{done ? "Fin" : "▶ Avanzar"}</Text>
            </Pressable>
          )}
        </View>
        <View style={s.metaRow}>
          <Text style={s.metaPill}>J {lg.current_jornada}/{lg.max_jornada}</Text>
          {data.my_budget != null && <Text style={[s.metaPill, { color: C.gold }]}>💰 {data.my_budget} M€</Text>}
          <Text style={s.metaPill}>{lg.join_code}</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 100 }}>
        {tab === "equipo" && <>
          <View style={s.court}>
            {POS.map((p, i) => {
              const pl = starters[i];
              return (
                <View key={i} style={[s.token, { left: p.l as any, top: p.t as any }]}>
                  <Image source={{ uri: pl ? photo(pl.feb_code) : "" }} style={[s.tokenImg, !pl && s.tokenEmpty]} />
                  <Text style={s.tokenName} numberOfLines={1}>{pl ? firstName(pl.name) : "Vacío"}</Text>
                  {pl && <Text style={s.tokenPrice}>{pl.price} M€</Text>}
                </View>
              );
            })}
          </View>
          <Text style={s.section}>TITULARES · {starters.length}/{lg.lineup_size}</Text>
          {starters.map((p) => <SquadCard key={p.player_id} p={p} busy={busy} onStar={() => toggleStarter(p.player_id, true)} onSell={() => act(() => api.sell(id, p.player_id))} />)}
          <Text style={s.section}>BANQUILLO · {bench.length}</Text>
          {bench.map((p) => <SquadCard key={p.player_id} p={p} busy={busy} onStar={() => toggleStarter(p.player_id, false)} onSell={() => act(() => api.sell(id, p.player_id))} />)}
          {squad.length === 0 && <Text style={[s.dim, { textAlign: "center", padding: 24 }]}>Aún no has fichado. Ve al Mercado.</Text>}
        </>}

        {tab === "mercado" && <>
          <TextInput style={s.input} placeholder="🔍 Buscar jugador…" placeholderTextColor={C.muted} value={q} onChangeText={setQ} />
          {market && <Text style={[s.dim, { fontSize: 12, marginBottom: 4 }]}>🎲 {market.market.length} libres esta jornada · {squad.length}/{lg.squad_size} tuyos · <Text style={{ color: C.gold }}>{market.my_budget} M€</Text></Text>}
          {market && <Text style={[s.dim, { fontSize: 11, marginBottom: 10 }]}>El mercado rota cada jornada. Cada jugador es exclusivo: si lo ficha alguien, desaparece.</Text>}
          {!market ? <ActivityIndicator color={C.orange} /> :
            market.market.filter((p: any) => p.name.toLowerCase().includes(q.toLowerCase())).map((p: any) => {
              const cant = p.owned || squad.length >= lg.squad_size || p.price > (market.my_budget ?? 0);
              const tr = p.form - p.val_avg;
              return (
                <View key={p.player_id} style={s.pcard}>
                  <Image source={{ uri: photo(p.feb_code) }} style={s.ph} />
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={s.pName} numberOfLines={1}>{firstName(p.name)}</Text>
                    <Text style={s.pTeam} numberOfLines={1}>{p.team}</Text>
                    <Text style={s.dim}>VAL <Text style={s.wht}>{p.val_avg}</Text>   +/- <Text style={s.wht}>{p.pm_avg > 0 ? "+" : ""}{p.pm_avg}</Text></Text>
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 5 }}>
                    <Text style={s.price}>{p.price}<Text style={s.cr}> M€</Text></Text>
                    <Text style={{ color: tr > 0.4 ? C.up : tr < -0.4 ? C.down : C.muted, fontWeight: "800", fontSize: 12 }}>{tr > 0.4 ? "▲" : tr < -0.4 ? "▼" : "◆"} {Math.abs(tr).toFixed(1)}</Text>
                    {p.owned ? <Text style={{ color: C.up, fontWeight: "800", fontSize: 12 }}>✓ Fichado</Text> :
                      <Pressable style={[s.buy, cant && s.btnOff]} disabled={busy || cant} onPress={() => act(() => api.buy(id, p.player_id), "Fichado ✓")}><Text style={s.buyTxt}>Fichar</Text></Pressable>}
                  </View>
                </View>
              );
            })}
        </>}

        {tab === "liga" && data.standings.map((r: any) => (
          <View key={r.member_id} style={[s.rankRow, r.rank === 1 && { borderColor: C.gold }]}>
            <Text style={s.rk}>{r.rank}</Text>
            <View style={{ flex: 1 }}>
              <Text style={s.wht}>{r.manager}</Text>
              <Text style={[s.dim, { fontSize: 11 }]}>{r.squad_count}/{lg.squad_size} jug · {r.squad_value} M€</Text>
            </View>
            <Text style={{ color: C.gold, fontWeight: "900", fontSize: 18 }}>{r.total_points}</Text>
          </View>
        ))}
      </ScrollView>

      {msg && <View style={s.toast}><View style={s.toastInner}><Text style={{ color: "#fff", fontWeight: "700" }}>{msg}</Text></View></View>}

      <View style={s.tabbar}>
        {([["equipo", "👥", "Equipo"], ["mercado", "🛒", "Mercado"], ["liga", "🏆", "Liga"]] as const).map(([k, ic, lb]) => (
          <Pressable key={k} style={[s.tab, tab === k && s.tabOn]} onPress={() => { setTab(k as any); if (k === "mercado" && !market) loadMarket(); }}>
            <Text style={{ fontSize: 17 }}>{ic}</Text>
            <Text style={[s.tabTxt, tab === k && { color: "#14203a" }]}>{lb}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function SquadCard({ p, busy, onStar, onSell }: any) {
  return (
    <View style={[s.pcard, p.starter && { borderColor: "rgba(255,176,32,0.5)" }]}>
      <Image source={{ uri: photo(p.feb_code) }} style={s.ph} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={s.pName} numberOfLines={1}>{firstName(p.name)}</Text>
        <Text style={s.pTeam} numberOfLines={1}>{p.team}</Text>
        <Text style={s.dim}>Compra {p.buy_price}  <Text style={{ color: p.delta >= 0 ? C.up : C.down }}>{p.delta >= 0 ? "▲" : "▼"} {Math.abs(p.delta)}</Text></Text>
      </View>
      <View style={{ alignItems: "flex-end", gap: 6 }}>
        <Text style={s.price}>{p.price}<Text style={s.cr}> M€</Text></Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Pressable disabled={busy} onPress={onStar}><Text style={{ fontSize: 19, opacity: p.starter ? 1 : 0.35 }}>⭐</Text></Pressable>
          <Pressable style={s.sell} disabled={busy} onPress={onSell}><Text style={{ color: C.down, fontWeight: "800", fontSize: 12 }}>Vender</Text></Pressable>
        </View>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: C.bg },
  logo: { fontSize: 26, fontWeight: "900", color: "#fff", letterSpacing: -0.5 },
  h1: { fontSize: 24, fontWeight: "900", color: "#fff", letterSpacing: -0.5 },
  dim: { color: C.dim, fontSize: 13 },
  wht: { color: "#fff" },
  section: { color: C.muted, fontWeight: "800", fontSize: 12, letterSpacing: 1, marginTop: 22, marginBottom: 10 },
  label: { color: C.dim, fontSize: 12, fontWeight: "700", marginBottom: 7, marginTop: 4 },
  input: { backgroundColor: C.card2, color: C.text, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 12, fontSize: 15, marginBottom: 12 },
  err: { color: C.down, marginBottom: 10 },
  panel: { backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 16, padding: 14 },
  segment: { flexDirection: "row", backgroundColor: C.card, borderRadius: 12, padding: 4, marginBottom: 18, width: 300 },
  segBtn: { flex: 1, paddingVertical: 9, borderRadius: 9, alignItems: "center" },
  segBtnOn: { backgroundColor: C.orange },
  segTxt: { color: C.dim, fontWeight: "800" },
  btn: { backgroundColor: C.orange, borderRadius: 12, paddingVertical: 13, alignItems: "center" },
  btnTxt: { color: "#14203a", fontWeight: "900", fontSize: 14 },
  btnSm: { backgroundColor: C.orange, borderRadius: 11, paddingVertical: 9, paddingHorizontal: 15 },
  btnGhost: { backgroundColor: C.card2, borderWidth: 1, borderColor: C.line },
  btnOff: { opacity: 0.4 },
  chip: { color: C.amber, backgroundColor: "rgba(255,106,43,0.16)", borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3, fontSize: 11, fontWeight: "800", overflow: "hidden" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 6 },
  pick: { backgroundColor: C.card2, borderColor: C.line, borderWidth: 1, borderRadius: 11, paddingHorizontal: 13, paddingVertical: 9 },
  pickOn: { backgroundColor: C.amber, borderColor: C.amber },
  pickTxt: { color: C.text, fontWeight: "700", fontSize: 13 },
  leagueCard: { backgroundColor: C.card2, borderColor: C.line, borderWidth: 1, borderRadius: 16, padding: 15, marginBottom: 11 },
  leagueName: { color: "#fff", fontWeight: "800", fontSize: 16 },
  leagueStats: { flexDirection: "row", gap: 8, marginTop: 12 },
  miniStat: { flex: 1, backgroundColor: "rgba(0,0,0,0.22)", borderRadius: 11, paddingVertical: 9, alignItems: "center" },
  miniV: { color: "#fff", fontWeight: "900", fontSize: 18 },
  miniK: { color: C.muted, fontSize: 9, fontWeight: "800", textTransform: "uppercase" },
  topbar: { paddingTop: 44, paddingHorizontal: 16, paddingBottom: 12, borderBottomColor: C.line, borderBottomWidth: 1, backgroundColor: "#0c1421" },
  metaRow: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  metaPill: { color: C.dim, backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6, fontSize: 12, fontWeight: "700", overflow: "hidden" },
  court: { backgroundColor: C.court, borderColor: C.line, borderWidth: 1, borderRadius: 16, height: 260, position: "relative", marginBottom: 6, overflow: "hidden" },
  token: { position: "absolute", width: 74, marginLeft: -37, marginTop: -30, alignItems: "center" },
  tokenImg: { width: 46, height: 46, borderRadius: 23, borderWidth: 2, borderColor: C.amber, backgroundColor: C.card2 },
  tokenEmpty: { borderColor: C.muted, opacity: 0.4, borderStyle: "dashed" },
  tokenName: { color: "#fff", fontSize: 10, fontWeight: "800", marginTop: 3 },
  tokenPrice: { color: C.gold, fontSize: 10, fontWeight: "900" },
  pcard: { flexDirection: "row", alignItems: "center", gap: 11, backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 15, padding: 10, marginBottom: 9 },
  ph: { width: 44, height: 54, borderRadius: 10, backgroundColor: C.card2 },
  pName: { color: "#fff", fontWeight: "800", fontSize: 14 },
  pTeam: { color: C.muted, fontSize: 11, marginBottom: 3 },
  price: { color: "#fff", fontWeight: "900", fontSize: 19 },
  cr: { color: C.muted, fontSize: 10, fontWeight: "700" },
  buy: { backgroundColor: C.orange, borderRadius: 9, paddingHorizontal: 14, paddingVertical: 6 },
  buyTxt: { color: "#14203a", fontWeight: "900", fontSize: 12 },
  sell: { backgroundColor: "rgba(255,93,108,0.14)", borderColor: "rgba(255,93,108,0.3)", borderWidth: 1, borderRadius: 9, paddingHorizontal: 10, paddingVertical: 6 },
  rankRow: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 13, padding: 12, marginBottom: 8 },
  rk: { width: 24, textAlign: "center", color: C.dim, fontWeight: "900", fontSize: 15 },
  tabbar: { position: "absolute", left: 14, right: 14, bottom: 16, flexDirection: "row", gap: 4, backgroundColor: "rgba(22,34,59,0.96)", borderColor: C.line, borderWidth: 1, borderRadius: 18, padding: 6 },
  tab: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 13, gap: 2 },
  tabOn: { backgroundColor: C.amber },
  tabTxt: { color: C.muted, fontWeight: "800", fontSize: 11 },
  toast: { position: "absolute", left: 0, right: 0, bottom: 92, alignItems: "center" },
  toastInner: { backgroundColor: C.card2, borderColor: C.line, borderWidth: 1, borderRadius: 13, paddingHorizontal: 18, paddingVertical: 11 },
});
