/* ============================================================================
   Apuestas de la jornada.

   Las prepara la liga y son iguales para todos. Se pueden combinar: al marcar varias,
   las cuotas se multiplican. Los topes (5 M€ jugados y 1 M€ ganados por jornada) se
   enseñan siempre, no en letra pequeña, porque son la mitad de las reglas.
   ========================================================================== */
import { useMemo, useState } from "react";
import { IconAlert, IconCheck, IconClose, IconCoin } from "../icons";
import { Empty, Section, SkeletonList } from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

export default function BetsTab({ data, busy, onBet }: {
  data: any; busy?: boolean; onBet: (ids: number[], stake: number) => void;
}) {
  const [sel, setSel] = useState<number[]>([]);
  const [stake, setStake] = useState(1);

  const opciones: any[] = data?.options ?? [];
  const cuota = useMemo(
    () => r1(sel.reduce((a, id) => a * (opciones.find((o) => o.id === id)?.odds ?? 1), 1) * 10) / 10,
    [sel, opciones]);

  if (!data) return <SkeletonList n={6} />;

  const libre = r1((data.stake_max ?? 5) - (data.stake_used ?? 0));
  const bruto = r1(stake * cuota - stake);
  const topado = bruto > (data.win_max ?? 1);
  const ganancia = Math.min(bruto, data.win_max ?? 1);
  const puedeApostar = data.open && sel.length > 0 && stake > 0 && stake <= libre
    && (data.bets_used ?? 0) < (data.bets_max ?? 3);

  const alternar = (id: number) =>
    setSel((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);

  return (
    <>
      <div className="betbar">
        <div>
          <span className="budget__k">Puedes jugar</span>
          <div className="budget__n">{libre} M€</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <span className="budget__k">Apuestas</span>
          <div className="budget__n">{data.bets_used}/{data.bets_max}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <span className="budget__k">Ganancia máx.</span>
          <div className="budget__n" style={{ color: "var(--accent)" }}>{data.win_max} M€</div>
        </div>
      </div>

      {!data.open && (
        <div className="notice notice--info">
          <span className="notice__ico"><IconAlert size={18} /></span>
          <div>
            <b>Las apuestas están cerradas</b>
            <span>La jornada ya ha empezado. Vuelven a abrirse en cuanto termine.</span>
          </div>
        </div>
      )}

      {opciones.length === 0
        ? <Empty icon={<IconCoin size={22} />} title="No hay apuestas para esta jornada">
            Hacen falta partidos con calendario y jugadores con recorrido para calcular
            las cuotas.
          </Empty>
        : <>
          <Section right={`jornada ${data.jornada}`}>Apuestas de la jornada</Section>
          {opciones.map((o) => {
            const on = sel.includes(o.id);
            return (
              <button key={o.id} className={"betopt" + (on ? " is-on" : "")}
                disabled={!data.open} onClick={() => alternar(o.id)}>
                <span className={"betopt__mark" + (on ? " is-on" : "")}>
                  {on && <IconCheck size={13} strokeWidth={3} />}
                </span>
                <span className="betopt__txt">
                  {o.label}
                  <small>{Math.round(o.prob * 100)} % de probabilidad</small>
                </span>
                <span className="betopt__odds num">{o.odds.toFixed(2)}</span>
              </button>
            );
          })}
        </>}

      {sel.length > 0 && data.open && (
        <div className="betslip">
          <div className="betslip__top">
            <span>{sel.length === 1 ? "Apuesta simple" : `Combinada de ${sel.length}`}</span>
            <b className="num">cuota {cuota.toFixed(2)}</b>
          </div>
          <div className="stepper" style={{ margin: "10px 0 8px" }}>
            <button className="stepper__btn" onClick={() => setStake((s) => Math.max(0.5, r1(s - 0.5)))}>−</button>
            <input type="number" step="0.5" value={stake} inputMode="decimal"
              onChange={(e) => setStake(Number(e.target.value))} />
            <button className="stepper__btn" onClick={() => setStake((s) => Math.min(libre, r1(s + 0.5)))}>+</button>
          </div>
          <p className="hint" style={{ margin: "0 0 10px" }}>
            Si aciertas cobras <b>{r1(stake + ganancia)} M€</b> ({ganancia} de ganancia).
            {topado && <> El tope de {data.win_max} M€ por jornada recorta lo que habrías
              ganado ({bruto} M€).</>}
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn--block" disabled={!puedeApostar || busy}
              onClick={() => { onBet(sel, stake); setSel([]); }}>
              <IconCoin size={17} />Apostar {stake} M€
            </button>
            <button className="btn btn--quiet" onClick={() => setSel([])}>
              <IconClose size={16} />
            </button>
          </div>
        </div>
      )}

      {(data.my_bets ?? []).length > 0 && <>
        <Section>Tus apuestas</Section>
        {data.my_bets.map((b: any) => (
          <div key={b.id} className={"betmine betmine--" + b.status}>
            <div className="betmine__top">
              <span className="betmine__j">J{b.jornada}</span>
              <span className="betmine__st">
                {b.status === "pending" ? `${b.stake} M€ · en juego`
                  : b.status === "won" ? `Ganada · +${r1(b.payout - b.stake)} M€`
                    : b.status === "void" ? `Anulada · ${b.payout} M€ devueltos`
                      : `Fallada · −${b.stake} M€`}
              </span>
              <span className="betmine__odds num">{b.odds.toFixed(2)}</span>
            </div>
            {b.legs.map((l: any, i: number) => (
              <div key={i} className={"betmine__leg leg--" + l.status}>
                {l.label}
                {l.result != null && <b> · hizo {l.result}</b>}
              </div>
            ))}
          </div>
        ))}
      </>}

      <p className="hint" style={{ marginTop: 14 }}>
        Las cuotas llevan un {Math.round((data.margin ?? 0.08) * 100)} % para la casa, así
        que a la larga apostar <b>resta</b> dinero: es lo que evita que la liga se llene de
        millones. Si un jugador no llega a jugar, esa parte se anula y se devuelve.
      </p>
    </>
  );
}
