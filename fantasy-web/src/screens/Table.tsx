/* ============================================================================
   Liga: qué hizo tu plantilla en cada jornada y las dos clasificaciones.
   ========================================================================== */
import { useEffect, useRef, useState } from "react";
import { IconChevronRight, IconTrophy } from "../icons";
import { PfBox } from "../parts";
import { Empty, Photo, Section, Segmented, prettyName, prettyTeam } from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

export default function TableTab({ data, lg, jr, onJornada, onManager, onPlayer }: any) {
  const rows: any[] = jr?.rows ?? [];
  const [view, setView] = useState<"jornada" | "general">(rows.length ? "jornada" : "general");

  return (
    <>
      <div style={{ margin: "4px 0 12px" }}>
        <Segmented value={view} onChange={setView} options={[
          { v: "jornada", label: "Por jornada" },
          { v: "general", label: "General" },
        ]} />
      </div>
      {view === "jornada"
        ? <JornadaView jr={jr} myId={data.my_member_id} onJornada={onJornada}
            onManager={onManager} onPlayer={onPlayer} />
        : <General data={data} lg={lg} onManager={onManager} />}
    </>
  );
}

/* ------------------------------------------------------------- por jornada */
function JornadaView({ jr, myId, onJornada, onManager, onPlayer }: any) {
  const rows: any[] = jr?.rows ?? [];
  const js: number[] = jr?.jornadas ?? [];
  const strip = useRef<HTMLDivElement>(null);

  // la jornada activa siempre a la vista en la tira
  useEffect(() => {
    const el = strip.current?.querySelector(".jchip.is-on") as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [jr?.jornada]);

  if (!rows.length) {
    return (
      <Empty icon={<IconTrophy size={22} />} title="Aún no hay ninguna jornada puntuada">
        Cuando se puntúe la primera verás aquí lo que hizo cada jugador de tu plantilla.
      </Empty>
    );
  }

  const me = rows.find((r) => r.member_id === myId);
  const leader = rows[0];
  const gap = me && leader ? r1(leader.points - me.points) : 0;
  const players: any[] = me?.players ?? [];
  // jornadas viejas: se puntuaron sin guardar el quinteto, así que no se puede decir quién
  // estaba alineado (y fingirlo con la plantilla de hoy hacía que el pasado cambiara solo)
  const known = me?.lineup_known !== false;
  const starters = known ? players.filter((p) => p.starter) : [];
  const bench = known ? players.filter((p) => !p.starter) : [];
  const top = (list: any[]) => list.reduce((a, p) => (p.points > (a?.points ?? -99) ? p : a), null as any);
  const best = top(starters);
  // el que se quedó fuera y lo habría cambiado todo: es la mitad de la gracia de mirar atrás
  const regret = top(bench);

  return (
    <>
      <div className="jstrip" ref={strip}>
        {js.map((j) => (
          <button key={j} className={"jchip" + (j === jr.jornada ? " is-on" : "")}
            onClick={() => onJornada(j)}>J{j}</button>
        ))}
      </div>

      {me && (
        <div className="jhero">
          <div style={{ flex: 1, minWidth: 0 }}>
            <span className="jhero__k">Tu jornada {jr.jornada}</span>
            <div className="jhero__v num">{me.points}<span>pts</span></div>
            <span className="jhero__note">
              {me.pos}º de {rows.length}
              {gap > 0 ? ` · a ${gap} del líder` : " · ¡ganaste la jornada!"}
            </span>
          </div>
          <div className="jhero__pos num">{me.pos}º</div>
        </div>
      )}

      {best && best.points > 0 && (
        <p className="hint" style={{ margin: "10px 2px 0" }}>
          Tu mejor titular fue <b>{prettyName(best.name)}</b> con <b>{r1(best.points)} PF</b>.
          {regret && regret.points > best.points && (
            <> Y en el banquillo se quedó <b>{prettyName(regret.name)}</b> con{" "}
              <b>{r1(regret.points)} PF</b>.</>
          )}
        </p>
      )}

      {known ? (
        <>
          <Section right={`${r1(starters.reduce((a, p) => a + p.points, 0))} pts`}>Tu quinteto</Section>
          {starters.map((p) => (
            <JornadaRow key={p.player_id} p={p} onOpen={() => onPlayer(p.player_id, jr.jornada)} />
          ))}
          {starters.length === 0 && <p className="hint">No tenías a nadie alineado.</p>}

          {bench.length > 0 && <>
            <Section right="no suman">Banquillo</Section>
            {bench.map((p) => (
              <JornadaRow key={p.player_id} p={p} bench onOpen={() => onPlayer(p.player_id, jr.jornada)} />
            ))}
          </>}

          <p className="hint" style={{ marginTop: 10 }}>
            Es el quinteto que tenías puesto esa jornada. Toca a cualquiera para ver su partido.
          </p>
        </>
      ) : (
        <>
          <Section right={`${me.points} pts`}>Tu plantilla esa jornada</Section>
          {players.map((p) => (
            <JornadaRow key={p.player_id} p={p} onOpen={() => onPlayer(p.player_id, jr.jornada)} />
          ))}
          <p className="hint" style={{ marginTop: 10 }}>
            Esta jornada se puntuó antes de que la liga empezara a guardar el quinteto, así que
            no se sabe a quién tenías alineado: lo que ves es tu plantilla, no el quinteto. Los
            <b> {me.points} puntos</b> sí son los que se guardaron ese día y no se van a mover.
          </p>
        </>
      )}

      <Section>Clasificación de la jornada</Section>
      <div className="podium">
        {rows.slice(0, 3).map((r: any) => (
          <button key={r.member_id} className={`pod pod--${r.pos}` + (r.member_id === myId ? " is-me" : "")}
            onClick={() => onManager(r)}>
            <span className="pod__pos num">{r.pos}</span>
            <span className="pod__name">{r.manager}</span>
            <span className="pod__pts num">{r.points}<span>pts</span></span>
          </button>
        ))}
      </div>
      {rows.length > 3 && (
        <div className="list">
          {rows.slice(3).map((r: any) => (
            <button key={r.member_id} className={"lrow lrow--tap" + (r.member_id === myId ? " is-me" : "")}
              onClick={() => onManager(r)}>
              <span className="lrow__pos">{r.pos}</span>
              <span className="lrow__who"><b>{r.manager}</b></span>
              <span className="lrow__pts">{r.points}</span>
              <IconChevronRight size={15} />
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function JornadaRow({ p, bench, onOpen }: { p: any; bench?: boolean; onOpen?: () => void }) {
  return (
    <div className={"prow" + (bench ? " prow--dim" : "") + (onOpen ? " prow--tap" : "")}
      onClick={onOpen} tabIndex={onOpen ? 0 : undefined}
      onKeyDown={(e) => { if (onOpen && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen(); } }}>
      <Photo code={p.feb_code} name={p.name} variant="sm" />
      <div className="prow__body">
        <div className="prow__name">{prettyName(p.name)}</div>
        <div className="prow__team">
          {prettyTeam(p.team)}{p.gone ? " · ya no lo tienes" : ""}
        </div>
      </div>
      {p.played
        ? <PfBox value={p.points} muted={bench} />
        : <span className="dnp">No jugó</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- general */
function General({ data, lg, onManager }: any) {
  return (
    <>
      <div className="list">
        {data.standings.map((r: any) => (
          <button key={r.member_id}
            className={"lrow lrow--tap" + (r.member_id === data.my_member_id ? " is-me" : "")}
            onClick={() => onManager({ member_id: r.member_id, manager: r.manager })}>
            <span className="lrow__pos">{r.rank}</span>
            <span className="lrow__who">
              <b>{r.manager}</b>
              <small>{r.squad_count}/{lg.squad_size} jugadores · {r.squad_value} M€ · {r.budget_remaining} M€ libres</small>
            </span>
            <span className="lrow__pts">{r.total_points}</span>
            <IconChevronRight size={15} />
          </button>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 12 }}>
        Toca un mánager para ver su plantilla, sus cláusulas y llevarte a alguien.
      </p>
    </>
  );
}
