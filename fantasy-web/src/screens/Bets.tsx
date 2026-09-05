/* ============================================================================
   Apuestas de la jornada.

   Las prepara la liga y son iguales para todos. Vienen repartidas en tres bandas
   (casi seguras, a cara o cruz y a lo loco) para que elegir signifique algo, y cada
   una se abre en una ficha con los números de los que sale la cuota: nadie debería
   apostar a ciegas a "más de 5 rebotes" sin ver cuántas veces los ha cogido. Se
   pueden combinar: al marcar varias, las cuotas se multiplican.

   Los topes (2 M€ jugados y 2 M€ ganados por jornada) se enseñan siempre, no en
   letra pequeña, porque son la mitad de las reglas.
   ========================================================================== */
import { useMemo, useState } from "react";
import { IconAlert, IconCheck, IconClose, IconCoin, IconTrophy } from "../icons";
import { Empty, Photo, Section, Sheet, SheetClose, SkeletonList } from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

/** Las tres bandas, en el orden en que se leen: de lo más probable a lo más loco. */
const BANDAS: [string, string, string][] = [
  ["segura", "Casi seguras", "Pagan poco, pero entran casi siempre"],
  ["normal", "A cara o cruz", "Aquí es donde de verdad hay que elegir"],
  ["loca", "A lo loco", "Casi nunca entran; por eso pagan lo que pagan"],
];

/** La foto del jugador o el escudo del equipo, según de qué vaya la apuesta. */
function Cara({ o, grande }: { o: any; grande?: boolean }) {
  if (o.kind === "stat") {
    return <Photo code={o.photo} name={o.detail?.nombre} variant={grande ? undefined : "sm"} />;
  }
  return (
    <div className={"crest" + (grande ? " crest--lg" : "")}>
      {o.logo ? <img src={o.logo} alt="" loading="lazy" />
        : <IconTrophy size={grande ? 24 : 17} />}
    </div>
  );
}

/** La línea de debajo del título: lo justo para decidir sin abrir la ficha. */
function resumenCorto(o: any): string {
  const pct = `${Math.round(o.prob * 100)} %`;
  const d = o.detail ?? {};
  if (o.kind === "stat" && d.de) return `${pct} · lo ha hecho ${d.veces} de ${d.de} partidos`;
  if (o.kind === "winner" && d.balance) {
    return `${pct} · ${d.balance.v}-${d.balance.d} · ${d.casa ? "en casa" : "fuera"}`;
  }
  return pct;
}

/* ============================================================== la pantalla */
export default function BetsTab({ data, busy, onBet }: {
  data: any; busy?: boolean; onBet: (ids: number[], stake: number) => void;
}) {
  const [sel, setSel] = useState<number[]>([]);
  const [stake, setStake] = useState(1);
  const [ficha, setFicha] = useState<any>(null);

  const opciones: any[] = data?.options ?? [];
  const cuota = useMemo(
    () => r1(sel.reduce((a, id) => a * (opciones.find((o) => o.id === id)?.odds ?? 1), 1) * 10) / 10,
    [sel, opciones]);

  if (!data) return <SkeletonList n={6} />;

  // nunca negativo: si alguien jugó de más con los topes viejos, se queda en cero
  const libre = Math.max(0, r1((data.stake_max ?? 2) - (data.stake_used ?? 0)));
  const bruto = r1(stake * cuota - stake);
  const tope = data.win_max ?? 2;
  const topado = bruto > tope;
  const ganancia = Math.min(bruto, tope);
  // con cuotas altas el tope llega enseguida: poner más de esto solo se arriesga
  const util = cuota > 1 ? Math.min(libre, r1(tope / (cuota - 1))) : libre;
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
          <div className="budget__n" style={{ color: "var(--accent)" }}>{tope} M€</div>
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
        : BANDAS.map(([banda, titulo, nota]) => {
          const suyas = opciones.filter((o) => (o.band ?? "normal") === banda);
          if (!suyas.length) return null;
          return (
            <div key={banda}>
              <Section right={banda === "segura" ? `jornada ${data.jornada}` : undefined}>
                {titulo}
              </Section>
              <p className="hint" style={{ margin: "-4px 0 9px" }}>{nota}</p>
              {suyas.map((o) => {
                const on = sel.includes(o.id);
                return (
                  <button key={o.id} className={"betopt" + (on ? " is-on" : "")}
                    onClick={() => setFicha(o)}>
                    <Cara o={o} />
                    <span className="betopt__txt">
                      {o.label}
                      <small>{resumenCorto(o)}</small>
                    </span>
                    <span className="betopt__end">
                      <span className="betopt__odds num">{o.odds.toFixed(2)}</span>
                      {on && <span className="betopt__on">
                        <IconCheck size={11} strokeWidth={3} />en juego
                      </span>}
                    </span>
                  </button>
                );
              })}
            </div>
          );
        })}

      {sel.length > 0 && data.open && (
        <div className="betslip">
          <div className="betslip__top">
            <span>{sel.length === 1 ? "Apuesta simple" : `Combinada de ${sel.length}`}</span>
            <b className="num">cuota {cuota.toFixed(2)}</b>
          </div>
          <div className="chiprow" style={{ margin: "10px 0 8px" }}>
            {[0.1, 0.5, 1, util].filter((v, i, a) => v > 0 && v <= libre && a.indexOf(v) === i)
              .sort((a, b) => a - b).map((v) => (
                <button key={v} className={"chip" + (stake === v ? " chip--accent" : "")}
                  onClick={() => setStake(v)}>
                  {v === util && util < libre ? <>{v} M€ · tope</> : <>{v} M€</>}
                </button>
              ))}
          </div>
          <div className="stepper" style={{ marginBottom: 8 }}>
            <button className="stepper__btn" onClick={() => setStake((s) => Math.max(0.1, r1(s - 0.1)))}>−</button>
            <input type="number" step="0.1" value={stake} inputMode="decimal"
              onChange={(e) => setStake(Number(e.target.value))} />
            <button className="stepper__btn" onClick={() => setStake((s) => Math.min(libre, r1(s + 0.1)))}>+</button>
          </div>
          <p className="hint" style={{ margin: "0 0 10px" }}>
            Si aciertas cobras <b>{r1(stake + ganancia)} M€</b> ({ganancia} de ganancia).
            {topado && <> Con {util} M€ ya te llevas el tope de {tope} M€: lo que pongas
              de más solo lo arriesgas.</>}
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

      {ficha && (
        <OptionSheet o={ficha} dentro={sel.includes(ficha.id)} abierto={Boolean(data.open)}
          onClose={() => setFicha(null)}
          onToggle={() => { alternar(ficha.id); setFicha(null); }} />
      )}
    </>
  );
}

/* ================================================================= la ficha */
function OptionSheet({ o, dentro, abierto, onClose, onToggle }: {
  o: any; dentro: boolean; abierto: boolean; onClose: () => void; onToggle: () => void;
}) {
  const d = o.detail ?? {};
  const banda = BANDAS.find(([b]) => b === (o.band ?? "normal"));

  return (
    <Sheet onClose={onClose} title={o.label}>
      <div className="sheet__head">
        <Cara o={o} grande />
        <div className="sheet__body">
          <h2>{o.label}</h2>
          <div className="dim" style={{ fontSize: "var(--fs-md)" }}>
            {o.kind === "stat"
              ? `${d.equipo ?? ""}${d.rival ? ` · ${d.casa ? "recibe a" : "visita a"} ${d.rival}` : ""}`
              : `${d.casa ? "En casa" : "Fuera"} contra ${d.rival}`}
          </div>
        </div>
        <SheetClose onClose={onClose} />
      </div>

      <div className="betbar">
        <div>
          <span className="budget__k">Cuota</span>
          <div className="budget__n" style={{ color: "var(--accent)" }}>{o.odds.toFixed(2)}</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <span className="budget__k">Probabilidad</span>
          <div className="budget__n">{Math.round(o.prob * 100)} %</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <span className="budget__k">Dificultad</span>
          <div className="budget__n" style={{ fontSize: "var(--fs-md)" }}>{banda?.[1]}</div>
        </div>
      </div>

      {o.kind === "stat" ? (
        <>
          <div className="ledger">
            <div>
              <span>Su media de {d.stat}</span>
              <b className="num">{d.media}</b>
            </div>
            <div>
              <span>Ha pasado de {d.linea}</span>
              <b className="num">{d.veces} de {d.de}</b>
            </div>
            <div>
              <span>Su mejor partido</span>
              <b className="num">{d.tope}</b>
            </div>
            <div>
              <span>Minutos por partido</span>
              <b className="num">{d.minutos}</b>
            </div>
          </div>

          {(d.ultimos ?? []).length > 0 && <>
            <Section>Sus últimos partidos</Section>
            <div className="chiprow">
              {d.ultimos.map((v: number, i: number) => (
                <span key={i} className={"chip" + (v > d.linea ? " chip--pos" : "")}>
                  <b>{v}</b>
                </span>
              ))}
            </div>
            <p className="hint" style={{ marginTop: 8 }}>
              El más reciente, primero. En verde, los partidos en los que esta apuesta
              habría entrado.
            </p>
          </>}
        </>
      ) : (
        <>
          <div className="ledger">
            <div>
              <span>{d.equipo}</span>
              <b className="num">{d.balance?.v}-{d.balance?.d}</b>
            </div>
            <div>
              <span>{d.rival}</span>
              <b className="num">{d.rival_balance?.v}-{d.rival_balance?.d}</b>
            </div>
            <div>
              <span>Diferencia media por partido</span>
              <b className="num">
                {(d.balance?.margen ?? 0) > 0 ? "+" : ""}{d.balance?.margen}
                <span className="muted"> vs {(d.rival_balance?.margen ?? 0) > 0 ? "+" : ""}{d.rival_balance?.margen}</span>
              </b>
            </div>
          </div>

          {(d.balance?.ultimos ?? []).length > 0 && <>
            <Section>Cómo llegan</Section>
            <div className="ledger">
              <div>
                <span>{d.equipo}</span>
                <span className="chiprow">
                  {d.balance.ultimos.map((r: string, i: number) => (
                    <span key={i} className={"chip " + (r === "V" ? "chip--pos" : "chip--neg")}><b>{r}</b></span>
                  ))}
                </span>
              </div>
              <div>
                <span>{d.rival}</span>
                <span className="chiprow">
                  {(d.rival_balance?.ultimos ?? []).map((r: string, i: number) => (
                    <span key={i} className={"chip " + (r === "V" ? "chip--pos" : "chip--neg")}><b>{r}</b></span>
                  ))}
                </span>
              </div>
            </div>
            <p className="hint" style={{ marginTop: 8 }}>El partido más reciente, primero.</p>
          </>}
        </>
      )}

      <p className="hint" style={{ marginTop: 14 }}>
        La probabilidad sale de estos números, y la cuota de la probabilidad menos la parte
        de la casa. Si {o.kind === "stat" ? "no llega a jugar" : "el partido se aplaza"},
        esta parte se anula y se devuelve.
      </p>

      <button className={"btn btn--block btn--lg" + (dentro ? " btn--quiet" : "")}
        style={{ marginTop: 14 }} disabled={!abierto} onClick={onToggle}>
        {dentro ? <><IconClose size={17} />Quitarla de la apuesta</>
          : <><IconCheck size={17} />Apostar a esto</>}
      </button>
    </Sheet>
  );
}
