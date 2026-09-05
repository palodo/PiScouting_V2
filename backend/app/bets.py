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

El menú se reparte en tres BANDAS a propósito (ver `BANDAS`): unas cuantas cantadas que
apenas pagan, unas cuantas a cara o cruz y alguna locura que casi nunca entra. Si todas
rondaran el 50% elegir daría igual y no habría nada que decidir.
"""
from __future__ import annotations

import json
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
CUOTA_MIN, CUOTA_MAX = 1.05, 15.0
STATS = {"pts": "puntos", "treb": "rebotes", "ast": "asistencias", "t3m": "triples"}

# El menú tiene que tener de todo: cantadas que casi no pagan, monedas al aire y alguna
# locura. Si todas rondaran el 50% todas se parecerían y elegir daría igual.
BANDAS = {
    "segura": (0.68, 0.88),
    "normal": (0.38, 0.62),
    "loca": (0.06, 0.22),
}
CUPOS = {"segura": 5, "normal": 6, "loca": 4}          # apuestas de jugador
CUPOS_GANADOR = {"segura": 2, "normal": 2, "loca": 1}  # y de quién gana el partido


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
    """Medias por jugador hasta la jornada dada (sin mirar el futuro).

    Guarda también el partido a partido: para decidir si una apuesta es segura o una
    locura no basta la media, hace falta saber cuántas veces ha pasado de verdad.
    """
    if not equipos:
        return {}
    rows = session.exec(
        select(PlayerMatchStat.player_id, PlayerMatchStat.pts, PlayerMatchStat.treb,
               PlayerMatchStat.ast, PlayerMatchStat.t3m, PlayerMatchStat.seconds,
               Player.name, Player.feb_code, PlayerMatchStat.team_id, Match.jornada_num)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .where(PlayerMatchStat.team_id.in_(equipos),
               Match.jornada_num != None,           # noqa: E711
               Match.jornada_num < hasta_jornada)).all()
    acum: dict[int, dict] = {}
    for pid, pts, treb, ast, t3m, seg, nombre, code, tid, jnum in rows:
        d = acum.setdefault(pid, {"n": 0, "pts": 0, "treb": 0, "ast": 0, "t3m": 0,
                                  "min": 0.0, "name": nombre, "code": code,
                                  "team_id": tid, "juegos": []})
        d["n"] += 1
        d["pts"] += pts or 0
        d["treb"] += treb or 0
        d["ast"] += ast or 0
        d["t3m"] += t3m or 0
        d["min"] += (seg or 0) / 60.0
        d["juegos"].append({"j": jnum or 0, "pts": pts or 0, "treb": treb or 0,
                            "ast": ast or 0, "t3m": t3m or 0,
                            "min": round((seg or 0) / 60.0), "team_id": tid})
    for d in acum.values():
        d["juegos"].sort(key=lambda g: g["j"])
        d["team_id"] = d["juegos"][-1]["team_id"] or d["team_id"]   # su equipo de ahora
    return acum


def _forma_equipos(session: Session, league: FantasyLeague, jornada: int) -> dict[int, list]:
    """Partido a partido de cada equipo hasta la jornada: diferencia y si ganó."""
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num != None,           # noqa: E711
                            Match.jornada_num < jornada,
                            Match.home_score != None)            # noqa: E711
    out: dict[int, list] = {}
    for m in session.exec(q).all():
        for tid, propio, ajeno in ((m.home_team_id, m.home_score, m.away_score),
                                   (m.away_team_id, m.away_score, m.home_score)):
            if tid:
                out.setdefault(tid, []).append(
                    {"j": m.jornada_num, "dif": (propio or 0) - (ajeno or 0)})
    for v in out.values():
        v.sort(key=lambda x: x["j"])
    return out


def _margen(forma: dict[int, list], team_id: Optional[int]) -> float:
    v = forma.get(team_id) or []
    return sum(x["dif"] for x in v) / len(v) if v else 0.0


def _balance(forma: dict[int, list], team_id: Optional[int]) -> dict:
    """Victorias-derrotas y las cinco últimas, para la ficha de la apuesta."""
    v = forma.get(team_id) or []
    ganados = sum(1 for x in v if x["dif"] > 0)
    return {"pj": len(v), "v": ganados, "d": len(v) - ganados,
            "margen": round(_margen(forma, team_id), 1),
            "ultimos": ["V" if x["dif"] > 0 else "D" for x in v[-5:]][::-1]}


def _rivales_de_la_jornada(session: Session, league: FantasyLeague,
                           jornada: int) -> dict[int, dict]:
    """team_id -> con quién juega esa jornada y si es en casa."""
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    out: dict[int, dict] = {}
    for m in session.exec(q).all():
        if not (m.home_team_id and m.away_team_id):
            continue
        local = session.get(Team, m.home_team_id)
        visit = session.get(Team, m.away_team_id)
        out[m.home_team_id] = {"rival_id": m.away_team_id,
                               "rival": _corto(visit.name) if visit else "?", "casa": True}
        out[m.away_team_id] = {"rival_id": m.home_team_id,
                               "rival": _corto(local.name) if local else "?", "casa": False}
    return out


def _linea_para(lam: float, lo: float, hi: float) -> Optional[int]:
    """La línea "más de k" cuya probabilidad cae dentro de la banda pedida.

    Al subir k la probabilidad baja, así que hay como mucho un tramo válido: de él nos
    quedamos con el que más se acerca al centro de la banda.
    """
    centro, mejor, mejor_d = (lo + hi) / 2, None, 9.9
    for k in range(0, 45):
        p = _poisson_mayor(lam, k)
        if lo <= p <= hi and abs(p - centro) < mejor_d:
            mejor, mejor_d = k, abs(p - centro)
        if p < lo:
            break
    return mejor


def generar_menu(session: Session, league: FantasyLeague, jornada: int) -> None:
    """Prepara las apuestas de la jornada si no están ya. Iguales para toda la liga."""
    ya = session.exec(select(FantasyBetOption).where(
        FantasyBetOption.league_id == league.id,
        FantasyBetOption.jornada == jornada).order_by(FantasyBetOption.id)).all()
    if ya and all(o.detail for o in ya):
        return
    if ya:
        # menú de la versión anterior (sin bandas ni datos). Se rehace, pero solo si
        # nadie ha apostado todavía: una apuesta en juego manda sobre cualquier mejora.
        jugadas = session.exec(select(FantasyBetLeg).where(
            FantasyBetLeg.option_id.in_([o.id for o in ya]))).first()
        if jugadas:
            return
        for o in ya:
            session.delete(o)
        session.commit()

    equipos = _jugadores_de_la_jornada(session, league, jornada)
    if not equipos:
        return
    medias = _medias(session, league, equipos, jornada)
    forma = _forma_equipos(session, league, jornada)
    rivales = _rivales_de_la_jornada(session, league, jornada)
    # solo gente con recorrido: con tres partidos la media no dice nada
    candidatos = [(pid, d) for pid, d in medias.items()
                  if d["n"] >= 5 and d["min"] / d["n"] >= 12]
    rng = random.Random(f"{league.id}:bets:{jornada}")
    rng.shuffle(candidatos)
    opciones: list[FantasyBetOption] = []
    faltan = dict(CUPOS)

    for pid, d in candidatos:
        if not any(v > 0 for v in faltan.values()):
            break
        # se empieza por la banda a la que más le falta, para que el menú salga variado
        for banda in sorted([b for b, n in faltan.items() if n > 0], key=lambda b: -faltan[b]):
            lo, hi = BANDAS[banda]
            posibles = []
            for stat in STATS:
                lam = d[stat] / d["n"]
                if lam < 1.2:          # líneas de "más de 0" no tienen gracia
                    continue
                k = _linea_para(lam, lo, hi)
                if k is not None:
                    posibles.append((stat, lam, k))
            if not posibles:
                continue
            stat, lam, linea = rng.choice(posibles)
            prob = _poisson_mayor(lam, linea)
            valores = [g[stat] for g in d["juegos"]]
            veces = sum(1 for v in valores if v > linea)
            info = rivales.get(d["team_id"]) or {}
            equipo = session.get(Team, d["team_id"]) if d["team_id"] else None
            opciones.append(FantasyBetOption(
                league_id=league.id, jornada=jornada, kind="stat", player_id=pid,
                team_id=d["team_id"], stat=stat, line=float(linea), band=banda,
                prob=round(prob, 4), odds=_cuota(prob),
                label=f"{_corto(d['name'])} · más de {linea} {STATS[stat]}",
                detail=json.dumps({
                    "nombre": _nombre_largo(d["name"]), "code": d["code"],
                    "equipo": _corto(equipo.name) if equipo else None,
                    "logo": equipo.logo if equipo else None,
                    "stat": STATS[stat], "linea": linea,
                    "media": round(lam, 1), "pj": d["n"],
                    "minutos": round(d["min"] / d["n"], 1),
                    "veces": veces, "de": len(valores),
                    "tope": max(valores) if valores else 0,
                    "ultimos": valores[-5:][::-1],
                    "rival": info.get("rival"), "casa": info.get("casa"),
                }, ensure_ascii=False)))
            faltan[banda] -= 1
            break

    # y quién gana cada partido, con la misma idea: alguna cantada y alguna sorpresa
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    partidos = list(session.exec(q).all())
    rng.shuffle(partidos)
    faltan_w = dict(CUPOS_GANADOR)
    for m in partidos:
        if not (m.home_team_id and m.away_team_id):
            continue
        if not any(v > 0 for v in faltan_w.values()):
            break
        p_local = _prob_local(forma, m)
        local, visit = session.get(Team, m.home_team_id), session.get(Team, m.away_team_id)
        for casa in (True, False):
            prob = p_local if casa else 1 - p_local
            banda = next((b for b, (lo, hi) in BANDAS.items()
                          if lo <= prob <= hi and faltan_w.get(b, 0) > 0), None)
            if not banda:
                continue
            equipo, rival = (local, visit) if casa else (visit, local)
            opciones.append(FantasyBetOption(
                league_id=league.id, jornada=jornada, kind="winner",
                team_id=equipo.id if equipo else None, match_id=m.id, band=banda,
                prob=round(prob, 4), odds=_cuota(prob),
                label=f"Gana {_corto(equipo.name if equipo else '?')} "
                      f"a {_corto(rival.name if rival else '?')}",
                detail=json.dumps({
                    "equipo": _corto(equipo.name) if equipo else "?",
                    "logo": equipo.logo if equipo else None,
                    "rival": _corto(rival.name) if rival else "?",
                    "rival_logo": rival.logo if rival else None,
                    "casa": casa,
                    "balance": _balance(forma, equipo.id if equipo else None),
                    "rival_balance": _balance(forma, rival.id if rival else None),
                }, ensure_ascii=False)))
            faltan_w[banda] -= 1
            break

    for o in opciones:
        session.add(o)
    if opciones:
        session.commit()


def _corto(nombre: str) -> str:
    """'A. PRIOR RUIZ' -> 'A. Prior'. Los nombres de la FEB vienen a gritos."""
    from .fantasy import _nice
    partes = _nice(nombre).split()
    return " ".join(partes[:2]) if len(partes) > 2 else " ".join(partes)


def _nombre_largo(nombre: str) -> str:
    from .fantasy import _nice
    return _nice(nombre)


def _prob_local(forma: dict[int, list], m: Match) -> float:
    """Probabilidad de que gane el local, por diferencia media de puntos y factor cancha."""
    esperado = (_margen(forma, m.home_team_id) - _margen(forma, m.away_team_id)) / 2 + 2.5
    return _normal_cdf(esperado / 11.0)      # 11 puntos de desviación típica


# ============================ apostar ============================
def _opcion_out(o: FantasyBetOption) -> dict:
    """Una apuesta tal y como la pinta la app: con foto, escudo y los números detrás."""
    d = json.loads(o.detail) if o.detail else {}
    return {"id": o.id, "kind": o.kind, "label": o.label, "odds": o.odds,
            "prob": o.prob, "player_id": o.player_id, "team_id": o.team_id,
            "stat": o.stat, "line": o.line, "band": o.band or "normal",
            "photo": d.get("code"), "logo": d.get("logo"), "detail": d}


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
        "options": [_opcion_out(o) for o in opciones],
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
