/* ============================================================================
   Todos los jugadores de la liga: buscar, ordenar y ver de quién es cada uno.

   Es el sitio al que se viene a comparar antes de pujar, ofertar o clausular, así que
   el orden por defecto es el que decide la liga: puntos fantasy.
   ========================================================================== */
import { useMemo, useState } from "react";
import { IconChevronRight, IconClose, IconSearch, IconSquad } from "../icons";
import { PlayerRow, fp } from "../parts";
import { Empty, Segmented, SkeletonList } from "../ui";

/* Dos de las vistas ordenan jugadores y la tercera cambia de sujeto: enseña a los
   mánagers. Están juntas porque responden a la misma pregunta —"¿quién tiene qué?"— y
   este es el sitio al que se viene a mirar antes de pujar o clausular. */
type Vista = "pf" | "precio" | "managers";
type Filtro = "todos" | "libres" | "mios";

const ORDENES: Record<"pf" | "precio", (a: any, b: any) => number> = {
  pf: (a, b) => fp(b) - fp(a),
  precio: (a, b) => b.price - a.price,
};

export default function PlayersTab({ data, liga, onOpen, onManager }: {
  data: any; liga: any; onOpen: (id: number) => void;
  onManager: (r: { member_id: number; manager: string }) => void;
}) {
  const [vista, setVista] = useState<Vista>("pf");
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [q, setQ] = useState("");

  const lista = useMemo(() => {
    const todos: any[] = data?.players ?? [];
    const aguja = q.trim().toLowerCase();
    return todos
      .filter((p) => {
        if (filtro === "libres" && p.owner_member_id) return false;
        if (filtro === "mios" && !p.mine) return false;
        if (aguja && !`${p.name} ${p.team} ${p.owner ?? ""}`.toLowerCase().includes(aguja)) return false;
        return true;
      })
      .sort(ORDENES[vista === "managers" ? "pf" : vista]);
  }, [data, vista, filtro, q]);

  const managers = useMemo(() => {
    const aguja = q.trim().toLowerCase();
    return (liga?.standings ?? []).filter((r: any) =>
      !aguja || String(r.manager).toLowerCase().includes(aguja));
  }, [liga, q]);

  if (!data) return <SkeletonList n={8} />;

  const libres = (data.players ?? []).filter((p: any) => !p.owner_member_id).length;

  return (
    <>
      <div className="searchbox">
        <IconSearch size={17} />
        <input className="searchbox__in" placeholder="Buscar jugador, equipo o mánager"
          value={q} onChange={(e) => setQ(e.target.value)} />
        {q && <button className="iconbtn" onClick={() => setQ("")} aria-label="Limpiar">
          <IconClose size={16} /></button>}
      </div>

      <Segmented<Vista> value={vista} onChange={setVista} options={[
        { v: "pf", label: "Puntos" },
        { v: "precio", label: "Valor" },
        { v: "managers", label: "Mánagers" },
      ]} />

      {vista !== "managers" && <div className="filters" style={{ marginTop: 10 }}>
        {([["todos", `Todos · ${data.players?.length ?? 0}`],
           ["libres", `Sin dueño · ${libres}`],
           ["mios", "Míos"]] as [Filtro, string][]).map(([v, label]) => (
          <button key={v} className={"filter" + (filtro === v ? " is-on" : "")}
            onClick={() => setFiltro(v)}>{label}</button>
        ))}
      </div>}

      {vista === "managers" ? (
        managers.length === 0
          ? <Empty icon={<IconSquad size={22} />} title="Ningún mánager con ese nombre" />
          : <>
              <div className="list" style={{ marginTop: 10 }}>
                {managers.map((r: any) => (
                  <button key={r.member_id}
                    className={"lrow lrow--tap" + (r.member_id === liga?.my_member_id ? " is-me" : "")}
                    onClick={() => onManager({ member_id: r.member_id, manager: r.manager })}>
                    <span className="lrow__pos">{r.rank}</span>
                    <span className="lrow__who">
                      <b>{r.manager}</b>
                      <small>{r.squad_count} jugadores · {r.squad_value} M€</small>
                    </span>
                    <span className="lrow__pts num">{r.total_points}</span>
                    <IconChevronRight size={15} />
                  </button>
                ))}
              </div>
              <p className="hint" style={{ marginTop: 12 }}>
                Toca a un mánager para ver su plantilla y sus cláusulas.
              </p>
            </>
      ) : lista.length === 0
        ? <Empty icon={<IconSquad size={22} />} title="Ningún jugador con esos filtros" />
        : lista.slice(0, 120).map((p: any, i: number) => (
          <PlayerRow key={p.player_id} p={p} onOpen={() => onOpen(p.player_id)}
            tone={p.mine ? "starter" : undefined}
            meta={<>
              <span className="prow__rank num">#{i + 1}</span>
              {p.owner
                ? <span className="prow__owner">{p.mine ? "tuyo" : p.owner}</span>
                : <span className="prow__free">Sin dueño</span>}
            </>} />
        ))}

      {vista !== "managers" && lista.length > 120 && (
        <p className="hint" style={{ marginTop: 12 }}>
          Se muestran los 120 primeros de {lista.length}. Afina con el buscador.
        </p>
      )}
    </>
  );
}
