/* ============================================================================
   La quiniela de la jornada.

   Sustituye a las apuestas con dinero, que en 48 mánagers se usaron UNA vez en toda la
   vida de la app: llevaban un 8% de margen para la casa, así que de media apostar perdía
   y la jugada óptima era no jugar. Aquí no se juega nada y se ganan puntos, así que
   participar siempre compensa.

   Lo que hace que haya partida es que cada acierto vale su cuota: clavar una locura de
   cuota 8 renta más que cinco cantadas de 1,1. Si todos los aciertos valieran igual, se
   elegirían siempre las cinco más fáciles y no habría nada que decidir.
   ========================================================================== */
import { useEffect, useState } from "react";
import { api } from "../api";
import { IconCheck, IconClose, IconTrophy } from "../icons";
import { Empty, Loading, Photo, Section } from "../ui";

const BANDAS: [string, string, string][] = [
  ["segura", "Cantadas", "Pagan poco, pero caen casi siempre"],
  ["normal", "A cara o cruz", "La mitad de las veces"],
  ["loca", "Locuras", "Casi nunca entran, y por eso pagan tanto"],
];

export default function QuinielaTab({ leagueId, myMemberId }: {
  leagueId: number; myMemberId?: number;
}) {
  const [d, setD] = useState<any>(null);
  const [sel, setSel] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const cargar = () => api.quiniela(leagueId).then((x: any) => {
    setD(x);
    setSel(x.mis_pronosticos.map((p: any) => p.option_id).filter(Boolean));
  }).catch(() => {});
  useEffect(() => { cargar(); }, [leagueId]);

  if (!d) return <Loading label="Cargando la quiniela" />;

  const { options = [], cuantos = 5, clasificacion = [], abierta, mis_pronosticos = [] } = d;
  const resueltos = mis_pronosticos.filter((p: any) => p.status !== "pending");
  const lleno = sel.length >= cuantos;

  function alternar(id: number) {
    if (!abierta) return;
    setSel((s) => s.includes(id) ? s.filter((x) => x !== id) : lleno ? s : [...s, id]);
    setMsg(null);
  }

  async function guardar() {
    setBusy(true);
    try {
      await api.guardarQuiniela(leagueId, sel);
      setMsg(`Guardado: ${sel.length} ${sel.length === 1 ? "pronóstico" : "pronósticos"}`);
      cargar();
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="qn__head">
        <div>
          <div className="qn__k">Quiniela de la jornada {d.jornada}</div>
          <div className="qn__n"><b className="num">{sel.length}</b> de {cuantos} elegidos</div>
        </div>
        {abierta
          ? <button className="btn btn--sm" disabled={busy} onClick={guardar}>
              {busy ? <span className="spinner" /> : "Guardar"}
            </button>
          : <span className="qn__lock">Cerrada</span>}
      </div>
      {msg && <p className="hint" style={{ marginTop: 8 }}>{msg}</p>}
      {!abierta && resueltos.length === 0 && mis_pronosticos.length === 0 && (
        <p className="hint" style={{ marginTop: 8 }}>
          Esta jornada se te pasó. La próxima abre en cuanto termine.
        </p>
      )}

      {/* Lo ya resuelto manda sobre el menú: es lo primero que se viene a mirar */}
      {resueltos.length > 0 && (
        <>
          <Section right={`${resueltos.filter((p: any) => p.status === "won").length}/${resueltos.length}`}>
            Cómo fue
          </Section>
          <div className="qn__list">
            {resueltos.map((p: any, i: number) => (
              <div key={i} className={"qn__done qn__done--" + p.status}>
                <span className="qn__ico">
                  {p.status === "won" ? <IconCheck size={15} /> : <IconClose size={15} />}
                </span>
                <span className="qn__dl">{p.label}
                  {p.result != null && <small> · hizo {p.result}</small>}
                </span>
                <span className="qn__dp num">{p.status === "won" ? `+${p.points}` : p.status === "void" ? "—" : "0"}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {abierta && BANDAS.map(([banda, titulo, pie]) => {
        const ops = options.filter((o: any) => o.band === banda);
        if (!ops.length) return null;
        return (
          <div key={banda}>
            <Section right={`×${ops[0].odds.toFixed(2)}–${ops[ops.length - 1].odds.toFixed(2)}`}>
              {titulo}
            </Section>
            <p className="hint" style={{ margin: "-4px 2px 8px" }}>{pie}</p>
            <div className="qn__list">
              {ops.map((o: any) => {
                const on = sel.includes(o.id);
                return (
                  <button key={o.id} className={"qn__o" + (on ? " is-on" : "")}
                    disabled={!on && lleno} onClick={() => alternar(o.id)}>
                    <Photo code={o.photo} name={o.label} variant="sm" />
                    <span className="qn__ol">{o.label}</span>
                    <span className="qn__od num">×{o.odds.toFixed(2)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}

      <Section right={String(clasificacion.length)}>Acertantes de la temporada</Section>
      {clasificacion.every((r: any) => r.jugados === 0) ? (
        <Empty icon={<IconTrophy size={22} />} title="Todavía no se ha resuelto ninguna">
          Elige {cuantos} pronósticos y vuelve cuando termine la jornada.
        </Empty>
      ) : (
        <div className="qn__tabla">
          {clasificacion.map((r: any) => (
            <div key={r.member_id} className={"qn__t" + (r.member_id === myMemberId ? " is-me" : "")}>
              <span className="qn__tp">{r.pos}</span>
              <span className="qn__tw">
                <b>{r.manager}</b>
                <small>{r.jugados
                  ? `${r.aciertos} de ${r.jugados} · ${r.acierto_pct}%`
                  : "sin pronósticos"}</small>
              </span>
              <span className="qn__ts num">{r.points}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
