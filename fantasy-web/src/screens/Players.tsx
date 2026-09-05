/* ============================================================================
   Todos los jugadores de la liga: buscar, ordenar y ver de quién es cada uno.

   Es el sitio al que se viene a comparar antes de pujar, ofertar o clausular, así que
   el orden por defecto es el que decide la liga: puntos fantasy.
   ========================================================================== */
import { useMemo, useState } from "react";
import { IconClose, IconSearch, IconSquad } from "../icons";
import { PlayerRow, fp } from "../parts";
import { Empty, Segmented, SkeletonList } from "../ui";

type Orden = "pf" | "precio" | "forma";
type Filtro = "todos" | "libres" | "mios";

const ORDENES: Record<Orden, (a: any, b: any) => number> = {
  pf: (a, b) => fp(b) - fp(a),
  precio: (a, b) => b.price - a.price,
  forma: (a, b) => (b.fp_form ?? 0) - (a.fp_form ?? 0),
};

export default function PlayersTab({ data, onOpen }: { data: any; onOpen: (id: number) => void }) {
  const [orden, setOrden] = useState<Orden>("pf");
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
      .sort(ORDENES[orden]);
  }, [data, orden, filtro, q]);

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

      <Segmented<Orden> value={orden} onChange={setOrden} options={[
        { v: "pf", label: "Puntos" },
        { v: "forma", label: "Forma" },
        { v: "precio", label: "Valor" },
      ]} />

      <div className="filters" style={{ marginTop: 10 }}>
        {([["todos", `Todos · ${data.players?.length ?? 0}`],
           ["libres", `Sin dueño · ${libres}`],
           ["mios", "Míos"]] as [Filtro, string][]).map(([v, label]) => (
          <button key={v} className={"filter" + (filtro === v ? " is-on" : "")}
            onClick={() => setFiltro(v)}>{label}</button>
        ))}
      </div>

      {lista.length === 0
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

      {lista.length > 120 && (
        <p className="hint" style={{ marginTop: 12 }}>
          Se muestran los 120 primeros de {lista.length}. Afina con el buscador.
        </p>
      )}
    </>
  );
}
