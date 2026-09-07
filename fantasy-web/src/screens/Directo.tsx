/* ============================================================================
   La jornada en vivo.

   Mientras se juega no se ficha, así que la pestaña del mercado no pinta nada y su sitio
   lo ocupa esta. Aquí está todo lo de la jornada: quién va ganando, con qué quinteto, y
   cómo van los partidos. Los que aún no se han disputado no enseñan marcador aunque la
   base ya sepa cómo acaban: destriparlos mataría la gracia de seguirla.
   ========================================================================== */
import { useEffect, useState } from "react";
import { api } from "../api";
import { IconAlert, IconTrophy } from "../icons";
import { Empty, Loading, Photo, Section, prettyName, prettyTeam } from "../ui";

export default function DirectoTab({ leagueId, myMemberId, onPlayer }: {
  leagueId: number; myMemberId?: number; onPlayer?: (id: number) => void;
}) {
  const [d, setD] = useState<any>(null);
  const [abierto, setAbierto] = useState<number | null>(null);

  useEffect(() => {
    let vivo = true;
    const traer = () => api.directo(leagueId).then((x) => vivo && setD(x)).catch(() => {});
    traer();
    // Se refresca solo: la jornada avanza mientras la miras y una pantalla congelada en
    // un directo se nota enseguida.
    const t = setInterval(traer, 20000);
    return () => { vivo = false; clearInterval(t); };
  }, [leagueId]);

  if (!d) return <Loading label="Cargando el directo" />;

  const { clasificacion = [], partidos = [], played = 0, total = 0 } = d;
  const jugados = partidos.filter((m: any) => m.home_score !== null);
  const pendientes = partidos.filter((m: any) => m.home_score === null);

  return (
    <>
      <div className="dir__head">
        <div>
          <div className="dir__k">Jornada {d.jornada} en juego</div>
          <div className="dir__n"><b className="num">{played}</b> de {total} partidos</div>
        </div>
        <div className="dir__bar" aria-hidden="true">
          <span style={{ width: `${total ? (played / total) * 100 : 0}%` }} />
        </div>
      </div>

      <Section right={`${clasificacion.length}`}>Clasificación de la jornada</Section>
      {clasificacion.length === 0 && (
        <Empty icon={<IconTrophy size={22} />} title="Todavía no hay nada que contar" />
      )}
      {clasificacion.map((r: any) => {
        const desplegado = abierto === r.member_id;
        return (
          <div key={r.member_id} className={"dir__m" + (r.member_id === myMemberId ? " is-me" : "")}>
            <button className="dir__row" onClick={() => setAbierto(desplegado ? null : r.member_id)}>
              <span className="dir__pos">{r.pos}</span>
              <span className="dir__who">
                <b>{r.manager}</b>
                <small>{r.por_jugar > 0
                  ? `${r.por_jugar} ${r.por_jugar === 1 ? "jugador" : "jugadores"} por jugar`
                  : "quinteto completo"}</small>
              </span>
              <span className="dir__pts num">{r.points}</span>
            </button>

            {desplegado && (
              <div className="dir__five">
                {r.jugadores.map((p: any) => (
                  <button key={p.player_id} className="dir__p"
                    onClick={() => onPlayer?.(p.player_id)}>
                    <Photo code={p.feb_code} name={p.name} variant="sm" />
                    <span className="dir__pb">
                      <b>{prettyName(p.name)}</b>
                      <small>{prettyTeam(p.team)}</small>
                    </span>
                    {p.points === null
                      ? <span className="dir__wait">por jugar</span>
                      : <span className="dir__pp num">{p.points}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}

      <Section right={`${jugados.length}/${partidos.length}`}>Partidos</Section>
      <div className="dir__games">
        {jugados.map((m: any) => (
          <div key={m.match_id} className="dir__g">
            <span className="dir__gt">{prettyTeam(m.home)}</span>
            <span className="dir__gs num">{m.home_score}<i>-</i>{m.away_score}</span>
            <span className="dir__gt dir__gt--a">{prettyTeam(m.away)}</span>
          </div>
        ))}
        {pendientes.map((m: any) => (
          <div key={m.match_id} className="dir__g dir__g--wait">
            <span className="dir__gt">{prettyTeam(m.home)}</span>
            <span className="dir__gs">por jugar</span>
            <span className="dir__gt dir__gt--a">{prettyTeam(m.away)}</span>
          </div>
        ))}
      </div>

      {pendientes.length > 0 && (
        <p className="hint" style={{ marginTop: 12 }}>
          <IconAlert size={13} /> Los puntos son provisionales: quedan {pendientes.length}
          {pendientes.length === 1 ? " partido" : " partidos"} por disputarse.
        </p>
      )}
    </>
  );
}
