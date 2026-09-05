/* ============================================================================
   Ofertas: las que te hacen por tus jugadores y las que haces tú por los de otros.

   Dos clases en la misma bandeja: las de la liga (cuando pones a alguien en venta) y
   las de otros mánagers. Se distinguen a la vista porque no se deciden igual: la de la
   liga es dinero seguro; la de un rival es un traspaso.
   ========================================================================== */
import { IconBolt, IconCheck, IconClose, IconCoin } from "../icons";
import { PlayerRow } from "../parts";
import { Empty, Section, useCountdown } from "../ui";

const r1 = (n: number) => Math.round(n * 10) / 10;

function Caduca({ iso, liga }: { iso?: string | null; liga?: boolean }) {
  const queda = useCountdown(iso);
  if (!iso || !queda) return null;
  // en las de la liga la cuenta atrás es la gracia del asunto: al agotarse llega otra
  return <span className={liga ? "prow__urge" : "prow__owner"}>
    {liga ? "vale " : "caduca en "}{queda}
  </span>;
}

export default function OffersTab({ data, busy, onOpen, onAccept, onReject }: {
  data: any; busy?: boolean;
  onOpen: (id: number) => void;
  onAccept: (o: any) => void;
  onReject: (o: any) => void;
}) {
  const recibidas: any[] = data?.received ?? [];
  const enviadas: any[] = data?.sent ?? [];

  if (!recibidas.length && !enviadas.length) {
    return (
      <Empty icon={<IconCoin size={22} />} title="No hay ofertas encima de la mesa">
        Pon a un jugador en venta y la liga te irá haciendo ofertas, o lánzale una tú a
        otro mánager desde la ficha de su jugador.
      </Empty>
    );
  }

  return (
    <>
      {recibidas.length > 0 && <>
        <Section right={String(recibidas.length)}>Te ofrecen</Section>
        {recibidas.some((o) => !o.from) && (
          <p className="hint" style={{ margin: "-4px 2px 10px" }}>
            Las ofertas de la liga <b>solo valen 24 horas</b>. Cuando entre la del día
            siguiente, esta desaparece: o la coges ahora, o te la juegas.
          </p>
        )}
        {recibidas.map((o) => {
          const dif = r1(o.amount - o.price);
          return (
            <div key={o.id} className="offer">
              <PlayerRow p={{ ...o, price: o.price }} onOpen={() => onOpen(o.player_id)}
                pf={o.fp_avg}
                meta={<>
                  <span className={"prow__owner" + (o.from ? "" : " prow__free")}>
                    {o.from ?? "La liga"}
                  </span>
                  <Caduca iso={o.expires_at} liga={!o.from} />
                </>} />
              <div className="offer__deal">
                <div>
                  <span className="offer__k">Te pagan</span>
                  <span className="offer__v num">{o.amount} M€</span>
                  <span className={"offer__dif " + (dif >= 0 ? "pos" : "neg")}>
                    {dif >= 0 ? "+" : "−"}{Math.abs(dif)} sobre su valor
                  </span>
                </div>
                <div className="offer__btns">
                  <button className="btn btn--sm btn--pos" disabled={busy}
                    onClick={() => onAccept(o)}><IconCheck size={15} />Aceptar</button>
                  <button className="btn btn--sm btn--quiet" disabled={busy}
                    onClick={() => onReject(o)}><IconClose size={15} />No</button>
                </div>
              </div>
            </div>
          );
        })}
      </>}

      {enviadas.length > 0 && <>
        <Section right={String(enviadas.length)}>Has ofrecido</Section>
        {enviadas.map((o) => (
          <PlayerRow key={o.id} p={{ ...o }} onOpen={() => onOpen(o.player_id)} pf={o.fp_avg}
            meta={<>
              <span className="prow__owner">de {o.to}</span>
              <Caduca iso={o.expires_at} />
            </>}
            right={<span className="chip chip--clause"><IconBolt size={11} strokeWidth={2.2} />
              {o.amount}</span>} />
        ))}
        <p className="hint" style={{ marginTop: 10 }}>
          Ese dinero queda apalabrado hasta que respondan: no puedes gastarlo dos veces.
        </p>
      </>}
    </>
  );
}
