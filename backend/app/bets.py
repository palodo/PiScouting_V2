"""Apuestas de la jornada.

Las prepara la liga (nadie inventa la suya) y salen del mismo sitio que todo lo demás:
los boxscores de la FEB. Dos reglas fijan el equilibrio de la economía:

  · MARGEN: la cuota lleva un 8% para la casa, así que de media apostar PIERDE dinero.
    Sin eso, apostar saldría neutro y la liga se llenaría de millones de la nada.
  · DOS TOPES, y son el MISMO número: como mucho 2 M€ jugados y 2 M€ de ganancia por
    jornada. Topar solo la ganancia no vale (bastaría con apostar 40 M€ a cuota 1,03
    para llevarse el tope casi sin riesgo), y dejar el tope de lo jugado por encima
    del de lo ganado tampoco: se podría arriesgar más de lo que se puede ganar, que es
    una apuesta perdida de antemano. Igualándolos, lo peor que puede pasar en una
    jornada es exactamente lo mejor, cambiado de signo.

Las probabilidades de "más de X" salen de una Poisson con la media del jugador, que es
la distribución que siguen los recuentos de un partido (puntos, rebotes, asistencias,
triples). Contrastado con la 2ª FEB ESTE: predice 52,3% donde la realidad dio 53,8%.
"""
from __future__ import annotations

import math
import random
from typing import Optional

from sqlmodel import Session, select

from .models import (FantasyBet, FantasyBetLeg, FantasyBetOption, FantasyLeague,
                     FantasyMember, Match, Player, PlayerMatchStat, Team)

MARGEN = 0.08          # se queda la casa; es lo que evita que la liga se infle
STAKE_MAX = 2.0        # M€ jugados por jornada y mánager
WIN_MAX = 2.0          # M€ de ganancia por jornada y mánager (el mismo: ver cabecera)
BETS_MAX = 3           # apuestas por jornada: es un extra, no el juego
CUOTA_MIN, CUOTA_MAX = 1.25, 6.0
STATS = {"pts": "puntos", "treb": "rebotes", "ast": "asistencias", "t3m": "triples"}


def _poisson_mayor(lam: float, k: int) -> float:
    """P(X > k) con media `lam`. Los recuentos de un partido se portan como Poisson."""
    if lam <= 0:
        return 0.0
    acum = 0.0
    for i in range(0, k + 1):
        acum += math.exp(-lam) * lam ** i / math.factorial(i)
    return max(0.0, min(1.0, 1 - acum))


def _cuota(prob: float) -> float:
    """Cuota justa (1/p) menos el margen de la casa, redondeada a dos decimales."""
    if prob <= 0.01:
        return CUOTA_MAX
    return round(max(CUOTA_MIN, min(CUOTA_MAX, (1 - MARGEN) / prob)), 2)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _jugadores_de_la_jornada(session: Session, league: FantasyLeague,
                             jornada: int) -> list[int]:
    """Equipos que juegan esa jornada -> jugadores candidatos."""
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    equipos = set()
    for m in session.exec(q).all():
        equipos.update(x for x in (m.home_team_id, m.away_team_id) if x)
    return list(equipos)


def _medias(session: Session, league: FantasyLeague, equipos: list[int],
            hasta_jornada: int) -> dict[int, dict]:
    """Medias por jugador hasta la jornada dada (sin mirar el futuro)."""
    if not equipos:
        return {}
    rows = session.exec(
        select(PlayerMatchStat.player_id, PlayerMatchStat.pts, PlayerMatchStat.treb,
               PlayerMatchStat.ast, PlayerMatchStat.t3m, PlayerMatchStat.seconds,
               Player.name, PlayerMatchStat.team_id)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .where(PlayerMatchStat.team_id.in_(equipos),
               Match.jornada_num != None,           # noqa: E711
               Match.jornada_num < hasta_jornada)).all()
    acum: dict[int, dict] = {}
    for pid, pts, treb, ast, t3m, seg, nombre, tid in rows:
        d = acum.setdefault(pid, {"n": 0, "pts": 0, "treb": 0, "ast": 0, "t3m": 0,
                                  "min": 0.0, "name": nombre, "team_id": tid})
        d["n"] += 1
        d["pts"] += pts or 0
        d["treb"] += treb or 0
        d["ast"] += ast or 0
        d["t3m"] += t3m or 0
        d["min"] += (seg or 0) / 60.0
    return acum


def generar_menu(session: Session, league: FantasyLeague, jornada: int) -> None:
    """Prepara las apuestas de la jornada si no están ya. Iguales para toda la liga."""
    ya = session.exec(select(FantasyBetOption).where(
        FantasyBetOption.league_id == league.id,
        FantasyBetOption.jornada == jornada)).first()
    if ya:
        return

    equipos = _jugadores_de_la_jornada(session, league, jornada)
    if not equipos:
        return
    medias = _medias(session, league, equipos, jornada)
    # solo gente con recorrido: con tres partidos la media no dice nada
    candidatos = [(pid, d) for pid, d in medias.items()
                  if d["n"] >= 5 and d["min"] / d["n"] >= 12]
    rng = random.Random(f"{league.id}:bets:{jornada}")
    rng.shuffle(candidatos)
    opciones: list[FantasyBetOption] = []

    for pid, d in candidatos:
        if len(opciones) >= 10:
            break
        stat = rng.choice(list(STATS.keys()))
        lam = d[stat] / d["n"]
        if lam < 1.2:                      # líneas de "más de 0" no tienen gracia
            continue
        # la línea que deja la probabilidad más cerca del 50%: ahí está lo interesante
        linea = min(range(0, 45), key=lambda k: abs(_poisson_mayor(lam, k) - 0.5))
        prob = _poisson_mayor(lam, linea)
        if not (0.30 <= prob <= 0.70):
            continue
        opciones.append(FantasyBetOption(
            league_id=league.id, jornada=jornada, kind="stat", player_id=pid,
            team_id=d["team_id"], stat=stat, line=float(linea), prob=round(prob, 4),
            odds=_cuota(prob),
            label=f"{_corto(d['name'])} · más de {linea} {STATS[stat]}"))

    # y quién gana cada partido
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    for m in session.exec(q).all():
        if not (m.home_team_id and m.away_team_id):
            continue
        p_local = _prob_local(session, league, m, jornada)
        if not (0.25 <= p_local <= 0.75):
            continue
        local = session.get(Team, m.home_team_id)
        visit = session.get(Team, m.away_team_id)
        gana_local = rng.random() < 0.5     # unas veces se ofrece el local y otras el visitante
        prob = p_local if gana_local else 1 - p_local
        equipo = local if gana_local else visit
        rival = visit if gana_local else local
        opciones.append(FantasyBetOption(
            league_id=league.id, jornada=jornada, kind="winner",
            team_id=equipo.id if equipo else None, match_id=m.id,
            prob=round(prob, 4), odds=_cuota(prob),
            label=f"Gana {_corto(equipo.name if equipo else '?')} "
                  f"a {_corto(rival.name if rival else '?')}"))

    for o in opciones:
        session.add(o)
    if opciones:
        session.commit()


def _corto(nombre: str) -> str:
    """'A. PRIOR RUIZ' -> 'A. Prior'. Los nombres de la FEB vienen a gritos."""
    from .fantasy import _nice
    partes = _nice(nombre).split()
    return " ".join(partes[:2]) if len(partes) > 2 else " ".join(partes)


def _prob_local(session: Session, league: FantasyLeague, m: Match, jornada: int) -> float:
    """Probabilidad de que gane el local, por diferencia de puntos media y factor cancha."""
    def margen(team_id: int) -> float:
        q = select(Match).where(Match.competition == league.competition,
                                Match.season == league.season,
                                Match.jornada_num < jornada,
                                Match.home_score != None)        # noqa: E711
        difs = []
        for x in session.exec(q).all():
            if x.home_team_id == team_id:
                difs.append((x.home_score or 0) - (x.away_score or 0))
            elif x.away_team_id == team_id:
                difs.append((x.away_score or 0) - (x.home_score or 0))
        return sum(difs) / len(difs) if difs else 0.0

    esperado = (margen(m.home_team_id) - margen(m.away_team_id)) / 2 + 2.5   # cancha
    return _normal_cdf(esperado / 11.0)      # 11 puntos de desviación típica


# ============================ apostar ============================
def resumen(session: Session, league: FantasyLeague, member: Optional[FantasyMember],
            jornada: int) -> dict:
    """El menú de la jornada y lo que lleva jugado el mánager."""
    generar_menu(session, league, jornada)
    opciones = session.exec(select(FantasyBetOption).where(
        FantasyBetOption.league_id == league.id,
        FantasyBetOption.jornada == jornada).order_by(FantasyBetOption.id)).all()
    mias = []
    jugado = ganancia = 0.0
    if member:
        for b in session.exec(select(FantasyBet).where(
                FantasyBet.league_id == league.id, FantasyBet.member_id == member.id)
                .order_by(FantasyBet.id.desc())).all():
            patas = session.exec(select(FantasyBetLeg).where(
                FantasyBetLeg.bet_id == b.id)).all()
            mias.append({
                "id": b.id, "jornada": b.jornada, "stake": b.stake, "odds": b.odds,
                "potential": b.potential, "status": b.status, "payout": b.payout,
                "legs": [{"label": l.label, "odds": l.odds, "status": l.status,
                          "result": l.result} for l in patas],
            })
            if b.jornada == jornada and b.status == "pending":
                jugado += b.stake
                ganancia += b.potential
    return {
        "jornada": jornada,
        "options": [{"id": o.id, "kind": o.kind, "label": o.label, "odds": o.odds,
                     "prob": o.prob, "player_id": o.player_id} for o in opciones],
        "my_bets": mias,
        "stake_used": round(jugado, 1), "stake_max": STAKE_MAX,
        "win_used": round(ganancia, 1), "win_max": WIN_MAX,
        "bets_used": len([b for b in mias if b["jornada"] == jornada and b["status"] == "pending"]),
        "bets_max": BETS_MAX, "margin": MARGEN,
    }


def apostar(session: Session, league: FantasyLeague, member: FantasyMember,
            jornada: int, option_ids: list[int], stake: float) -> dict:
    """Juega una apuesta simple o combinada."""
    from .fantasy import _log, _require, utcnow
    _require(session, league, "mercado", "alineacion", what="podrás apostar")

    stake = round(float(stake), 1)
    if stake <= 0:
        raise ValueError("Tienes que apostar algo")
    if not option_ids:
        raise ValueError("Elige al menos una apuesta")
    if len(set(option_ids)) != len(option_ids):
        raise ValueError("No puedes repetir la misma apuesta en una combinada")

    est = resumen(session, league, member, jornada)
    if est["bets_used"] >= BETS_MAX:
        raise ValueError(f"Máximo {BETS_MAX} apuestas por jornada")
    if est["stake_used"] + stake > STAKE_MAX + 1e-6:
        libre = round(STAKE_MAX - est["stake_used"], 1)
        raise ValueError(f"Tope de {STAKE_MAX} M€ por jornada: te quedan {libre} M€")
    if stake > member.budget_remaining + 1e-6:
        raise ValueError("No tienes ese dinero")

    opciones = []
    for oid in option_ids:
        o = session.get(FantasyBetOption, oid)
        if not o or o.league_id != league.id or o.jornada != jornada:
            raise ValueError("Esa apuesta ya no está disponible")
        opciones.append(o)

    cuota = 1.0
    for o in opciones:
        cuota *= o.odds
    cuota = round(cuota, 2)
    # El tope de ganancia NO bloquea apuestas nuevas: se aplica al cobrar, sumando todo
    # lo que ganes esa jornada. Bloquearlo aqui hacia que la primera apuesta decente se
    # comiera el cupo entero y ya no dejara jugar mas, que era justo lo contrario de
    # "puedes hacer hasta tres y combinarlas".
    bruto = round(stake * cuota - stake, 1)
    ganancia = min(bruto, WIN_MAX)

    member.budget_remaining = round(member.budget_remaining - stake, 1)
    session.add(member)
    bet = FantasyBet(league_id=league.id, member_id=member.id, jornada=jornada,
                     stake=stake, odds=cuota, potential=ganancia)
    session.add(bet)
    session.commit()
    session.refresh(bet)
    for o in opciones:
        session.add(FantasyBetLeg(bet_id=bet.id, option_id=o.id, label=o.label,
                                  odds=o.odds))
    session.commit()
    return {"ok": True, "odds": cuota, "potential": ganancia,
            "capped": ganancia < bruto, "budget_remaining": member.budget_remaining}


def _resultado_pata(session: Session, league: FantasyLeague, o: FantasyBetOption,
                    jornada: int) -> tuple[str, Optional[float]]:
    """(estado, dato) de una pata ya jugada. 'void' si no hay con qué resolverla."""
    if o.kind == "stat":
        filas = session.exec(
            select(PlayerMatchStat, Match)
            .join(Match, Match.id == PlayerMatchStat.match_id)
            .where(PlayerMatchStat.player_id == o.player_id,
                   Match.jornada_num == jornada)).all()
        if not filas:
            return "void", None          # no jugó: se devuelve el dinero
        total = sum(getattr(st, o.stat) or 0 for st, _ in filas)
        return ("won" if total > (o.line or 0) else "lost"), float(total)
    if o.kind == "winner":
        m = session.get(Match, o.match_id) if o.match_id else None
        if not m or m.home_score is None or m.away_score is None:
            return "void", None          # aplazado
        gana_local = m.home_score > m.away_score
        acierta = (o.team_id == m.home_team_id) == gana_local
        # la diferencia, vista desde el equipo por el que se apostó: un "+8" se entiende
        # solo, un "-8" en una apuesta ganada no hay quien lo lea
        dif = m.home_score - m.away_score
        if o.team_id != m.home_team_id:
            dif = -dif
        return ("won" if acierta else "lost"), float(dif)
    return "void", None


def resolver(session: Session, league: FantasyLeague, jornada: int) -> dict:
    """Liquida las apuestas de una jornada. Lo llama `advance` al puntuarla.

    El tope de ganancia se aplica aqui, sobre lo que se cobra, y REPARTIDO EN PROPORCION
    entre las apuestas acertadas. Hacerlo por orden de liquidacion era injusto y encima
    confuso: la primera se llevaba el millon entero y las demas aparecian como ganadas
    pero pagando cero.
    """
    from .fantasy import _log, _notify, utcnow
    pendientes = session.exec(select(FantasyBet).where(
        FantasyBet.league_id == league.id, FantasyBet.jornada == jornada,
        FantasyBet.status == "pending")).all()
    if not pendientes:
        return {"ganadas": 0, "perdidas": 0, "anuladas": 0}

    # --- primera pasada: que ha hecho cada pata ---
    bruto: dict[int, float] = {}          # bet_id -> ganancia sin topar
    estado: dict[int, str] = {}
    for b in pendientes:
        patas = session.exec(select(FantasyBetLeg).where(FantasyBetLeg.bet_id == b.id)).all()
        cuota_viva, fallo, vivas = 1.0, False, 0
        for l in patas:
            o = session.get(FantasyBetOption, l.option_id) if l.option_id else None
            res, dato = _resultado_pata(session, league, o, jornada) if o else ("void", None)
            l.status, l.result = res, dato
            session.add(l)
            if res == "lost":
                fallo = True
            elif res == "won":
                cuota_viva *= l.odds
                vivas += 1
        if fallo:
            estado[b.id] = "lost"
        elif vivas == 0:
            estado[b.id] = "void"          # nadie jugo: se devuelve lo apostado
        else:
            estado[b.id] = "won"
            bruto[b.id] = round(b.stake * cuota_viva - b.stake, 1)

    # --- cuanto gana cada manager, ya topado ---
    por_manager: dict[int, float] = {}
    for b in pendientes:
        if estado[b.id] == "won":
            por_manager[b.member_id] = por_manager.get(b.member_id, 0.0) + bruto[b.id]
    factor = {mid: (WIN_MAX / total if total > WIN_MAX else 1.0)
              for mid, total in por_manager.items()}

    ganadas = perdidas = anuladas = 0
    for b in pendientes:
        m = session.get(FantasyMember, b.member_id)
        if estado[b.id] == "lost":
            b.status, b.payout = "lost", 0.0
            perdidas += 1
            if m:
                _notify(session, league, m, "bet", "Apuesta fallada",
                        f"Se van {b.stake} M€ de la jornada {jornada}")
        elif estado[b.id] == "void":
            b.status, b.payout = "void", b.stake
            anuladas += 1
            if m:
                m.budget_remaining = round(m.budget_remaining + b.stake, 1)
                session.add(m)
                _notify(session, league, m, "bet", "Apuesta anulada",
                        f"No llegaron a jugar: te devolvemos {b.stake} M€")
        else:
            f = factor.get(b.member_id, 1.0)
            ganancia = round(bruto[b.id] * f, 1)
            b.status = "won"
            b.payout = round(b.stake + ganancia, 1)
            ganadas += 1
            if m:
                m.budget_remaining = round(m.budget_remaining + b.payout, 1)
                session.add(m)
                extra = (f" (tope de {WIN_MAX} M€ por jornada)" if f < 1 else "")
                _notify(session, league, m, "bet", f"¡Apuesta ganada! +{ganancia} M€",
                        f"Jornada {jornada} · cobras {b.payout} M€{extra}")
                _log(session, league.id, "bet",
                     f"🎯 {m.manager_name} acierta su apuesta de la jornada "
                     f"{jornada} y gana {ganancia} M€")
        b.resolved_at = utcnow()
        session.add(b)
    session.commit()
    return {"ganadas": ganadas, "perdidas": perdidas, "anuladas": anuladas}
