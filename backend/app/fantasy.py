"""Fantasy FEB — motor de ligas por conferencia con mercado de subastas (estilo Biwenger).

La liga gira en torno a la JORNADA y pasa por tres fases (ver `league_state`):

  1. MERCADO — desde que acaba la jornada anterior hasta `market_close_before_h` horas antes
     del primer partido de la siguiente (24 h por defecto: el día antes). Cada día sale una
     tanda nueva de `market_size` jugadores libres, elegidos al azar pero repartidos por
     tramos de precio. Se PUJA en secreto (se ve cuánta gente puja, no el importe) y al
     cerrar cada tanda gana la puja más alta (a igualdad, la primera). Aquí también se ficha
     por cláusula y se vende.
  2. ALINEACIÓN — mercado ya cerrado, pero el quinteto se puede cambiar hasta el primer salto.
  3. JORNADA — se está jugando: no se toca NADA (ni quinteto, ni pujas, ni cláusulas) hasta
     que termine. Si hay partidos aplazados la jornada sigue abierta hasta que se disputen.
     Cuando acaba se puntúa sola y se vuelve a la fase de mercado.

Todo se resuelve de forma perezosa (`sync_market`) en cada petición: no hace falta ningún
proceso en segundo plano.

Modo simulación (`sim_mode`): la temporada de la BBDD ya está jugada, así que las fechas
reales de los partidos no sirven de reloj. La liga usa su propio calendario semanal
(`play_weekday` + `play_hour`) y las estadísticas se recortan siempre a `current_jornada`,
que es lo que evita enseñar partidos que en la liga "aún no se han jugado".

La valoración de jugadores es dinámica (VAL + forma + /- ponderado por fiabilidad) y los
puntos de cada jornada son la VAL del jugador + bonus si su equipo ganó.
"""
from __future__ import annotations

import json
import random
import string
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text as sa_text  # alias: `text` ya se usa como nombre de parámetro
from sqlmodel import Session, select

from .config import FANTASY_COMPETITIONS
from .models import (
    Team, Player, Match, PlayerMatchStat,
    FantasyLeague, FantasyMember, FantasyPick, FantasyListing, FantasyBid, FantasyEvent,
    FantasyNotification, FantasyOffer,
    FantasyJornadaScore, FantasyLineup,
)

try:  # hora peninsular para el horario del mercado
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - si falta tzdata, se usa UTC
    TZ = timezone.utc

# --- parámetros del modelo de precio ---
PRICE_K = 1.1
PRICE_MIN = 1.0
PRICE_MAX = 25.0
RECENT_N = 4  # partidos para la "forma reciente"
# Partidos de la temporada en curso a partir de los cuales el precio deja de mirar a la
# anterior. Antes de eso se mezclan: en la jornada 1 el precio es casi todo del año pasado,
# porque un solo partido no dice nada. Sin esto, al empezar la temporada todos los
# jugadores valdrían PRICE_MIN y el primer mercado no tendría ningún sentido.
BLEND_GAMES = 6
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _pct(m, a):
    return round(100.0 * m / a, 1) if a else 0.0


# ============================ datos de la conferencia ============================
def conference_games(session: Session, comp: str, grupo: Optional[str], season: str) -> dict:
    """player_id -> {name, feb_code, team_id, team, games:[...]} ordenado por jornada.

    Cada partido lleva val, +/-, minutos y el margen final del equipo: los minutos y el
    margen son los que permiten valorar el +/- en su contexto (ver `_pm_bonus`).
    """
    # Se piden columnas sueltas y no entidades: con objetos del ORM, 3ª FEB (unas 40.000
    # líneas de boxscore) llegaba a 247 MB de pico, y el plan gratuito de Render tiene 512.
    q = (
        select(Player.id, Player.name, Player.feb_code, Team.id, Team.name,
               Match.jornada_num, Match.home_score, Match.away_score,
               PlayerMatchStat.is_home, PlayerMatchStat.val, PlayerMatchStat.plus_minus,
               PlayerMatchStat.seconds, PlayerMatchStat.match_id)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(Team.competition == comp, Team.season == season)
    )
    if grupo:
        q = q.where(Team.grupo == grupo)
    out: dict[int, dict] = {}
    for (pid, pname, feb_code, tid, tname, jornada_num,
         home_score, away_score, is_home, val, pm, seconds, mid) in session.exec(q):
        if jornada_num is None:
            continue
        my = home_score if is_home else away_score
        opp = away_score if is_home else home_score
        won = my is not None and opp is not None and my > opp
        margin = (my - opp) if (my is not None and opp is not None) else 0
        d = out.setdefault(pid, {
            "player_id": pid, "name": pname, "feb_code": feb_code,
            "team_id": tid, "team": tname, "last_j": jornada_num, "games": [],
        })
        # Con traspasos y jugadores vinculados (159 en la 25/26) el equipo bueno es el del
        # partido más reciente, no el que la base devuelva primero.
        if jornada_num >= d["last_j"]:
            d["last_j"] = jornada_num
            d["team_id"] = tid
            d["team"] = tname
        d["games"].append({"j": jornada_num, "val": val, "pm": pm, "won": won, "mid": mid,
                           "min": round((seconds or 0) / 60.0, 1), "margin": margin})
    for d in out.values():
        d["games"].sort(key=lambda g: g["j"])
    return out


def departed_players(session: Session, comp: str, grupo: Optional[str], season: str) -> set[int]:
    """Jugadores que se han marchado de la conferencia a mitad de temporada.

    Un fichaje en enero deja al mánager que lo tenía con un jugador que ya no puntúa, así
    que hay que poder avisarle. Se compara por FECHA y no por jornada, porque las jornadas
    de dos competiciones no caen el mismo fin de semana: si su último partido fuera de la
    conferencia es posterior al último dentro, es que se ha ido (y no que esté lesionado).
    """
    rows = session.exec(sa_text(f"""
        WITH aqui AS (
            SELECT s.player_id, MAX(m.match_date) AS last_date
            FROM player_match_stats s
            JOIN matches m ON m.id = s.match_id
            JOIN teams t ON t.id = s.team_id
            WHERE t.season = :season AND t.competition = :comp
                  {"AND t.grupo = :grupo" if grupo else ""}
                  AND m.match_date IS NOT NULL
            GROUP BY s.player_id
        ),
        fuera AS (
            SELECT s.player_id, MAX(m.match_date) AS last_date
            FROM player_match_stats s
            JOIN matches m ON m.id = s.match_id
            JOIN teams t ON t.id = s.team_id
            WHERE t.season = :season
                  AND NOT (t.competition = :comp {"AND t.grupo = :grupo" if grupo else ""})
                  AND m.match_date IS NOT NULL
            GROUP BY s.player_id
        )
        SELECT a.player_id FROM aqui a
        JOIN fuera f ON f.player_id = a.player_id
        WHERE f.last_date > a.last_date
    """), params={"season": season, "comp": comp, **({"grupo": grupo} if grupo else {})}).all()
    return {r[0] for r in rows}


def season_progress(session: Session, comp: str, grupo: Optional[str], season: str) -> dict:
    """Por dónde va la temporada REAL de esa conferencia.

    `live` es True mientras queden partidos por jugarse: es lo que decide si una liga nueva
    se juega contra el calendario de verdad o en simulación (la 25/26 está entera, así que
    ahí no hay nada que esperar y toca repetirla jornada a jornada).
    """
    q = select(Match).where(Match.competition == comp, Match.season == season)
    if grupo:
        q = q.where(Match.grupo == grupo)
    played, pending, mj = set(), set(), 0
    for m in session.exec(q).all():
        if m.jornada_num is None:
            continue
        mj = max(mj, m.jornada_num)
        (played if m.home_score is not None and m.away_score is not None else pending).add(
            m.jornada_num)
    # una jornada cuenta como jugada solo si NINGÚN partido suyo falta
    completas = played - pending
    return {"max_jornada": mj, "last_played": max(completas, default=0),
            "live": bool(pending)}


def max_jornada(session: Session, comp: str, grupo: Optional[str], season: str) -> int:
    q = select(Match).where(Match.competition == comp, Match.season == season)
    if grupo:
        q = q.where(Match.grupo == grupo)
    js = [m.jornada_num for m in session.exec(q).all() if m.jornada_num is not None]
    return max(js) if js else 0


# ============================ precio ============================
def _price_from_games(games: list[dict], up_to_j: int, team_games: int) -> float:
    played = [g for g in games if g["j"] <= up_to_j]
    if not played:
        return PRICE_MIN
    n = len(played)
    val_cum = sum(g["val"] for g in played) / n
    pm_cum = sum(g["pm"] for g in played) / n
    recent = played[-RECENT_N:]
    val_recent = sum(g["val"] for g in recent) / len(recent)
    reliab = min(1.0, n / max(1.0, 0.5 * team_games))
    raw = 0.6 * val_cum + 0.4 * val_recent + 0.3 * pm_cum
    return round(_clamp(PRICE_K * raw * (0.5 + 0.5 * reliab), PRICE_MIN, PRICE_MAX), 1)


def previous_season(season: str) -> str:
    """'2026' -> '2025'. Cadena vacía si la temporada no es un año."""
    try:
        return str(int(season) - 1)
    except (TypeError, ValueError):
        return ""


# Los precios de una temporada cerrada no cambian nunca, así que se calculan una vez por
# proceso. Sin esto habría que recorrer todos sus boxscores en cada consulta del mercado.
_SEASON_PRICES: dict[str, dict[int, float]] = {}


def season_prices(session: Session, season: str) -> dict[int, float]:
    """Precio de cada jugador con una temporada COMPLETA, sea cual sea su competición.

    No se filtra por conferencia a propósito: un jugador puede haber ascendido o bajado de
    categoría, y su valoración del año pasado sigue siendo la mejor pista que tenemos.
    """
    if not season:
        return {}
    if season in _SEASON_PRICES:
        return _SEASON_PRICES[season]

    # Se agrega en la base y no en Python: traer los ~55.000 boxscores de una temporada
    # para promediarlos aquí costaba segundos contra Postgres. Así vuelven ~3.000 filas.
    rows = session.exec(sa_text("""
        WITH g AS (
            SELECT s.player_id, s.team_id, s.val, s.plus_minus, m.jornada_num,
                   ROW_NUMBER() OVER (PARTITION BY s.player_id
                                      ORDER BY m.jornada_num DESC) AS rn
            FROM player_match_stats s
            JOIN matches m ON m.id = s.match_id
            JOIN teams t ON t.id = s.team_id
            WHERE t.season = :season AND m.jornada_num IS NOT NULL
        ),
        tg AS (
            SELECT s.team_id, COUNT(DISTINCT m.jornada_num) AS n
            FROM player_match_stats s
            JOIN matches m ON m.id = s.match_id
            JOIN teams t ON t.id = s.team_id
            WHERE t.season = :season AND m.jornada_num IS NOT NULL
            GROUP BY s.team_id
        )
        -- MAX(tg.n): hay jugadores vinculados que juegan en dos equipos la misma temporada
        -- (incluso en la misma jornada). Se toma el equipo con más jornadas para que la
        -- fiabilidad no dependa del orden en que la base devuelva las filas.
        SELECT g.player_id,
               COUNT(*) AS n,
               AVG(g.val * 1.0) AS val_cum,
               AVG(g.plus_minus * 1.0) AS pm_cum,
               AVG(CASE WHEN g.rn <= :recent THEN g.val * 1.0 END) AS val_recent,
               MAX(tg.n) AS team_games
        FROM g JOIN tg ON tg.team_id = g.team_id
        GROUP BY g.player_id
    """), params={"season": season, "recent": RECENT_N}).all()

    out: dict[int, float] = {}
    for pid, n, val_cum, pm_cum, val_recent, team_games in rows:
        reliab = min(1.0, n / max(1.0, 0.5 * (team_games or n)))
        raw = 0.6 * float(val_cum) + 0.4 * float(val_recent) + 0.3 * float(pm_cum)
        out[pid] = round(_clamp(PRICE_K * raw * (0.5 + 0.5 * reliab), PRICE_MIN, PRICE_MAX), 1)

    _SEASON_PRICES[season] = out
    return out


# Los precios son iguales para todas las ligas de la misma conferencia y jornada, y solo
# cambian al avanzar jornada o al ingerir partidos nuevos. Calcularlos exige recorrer los
# boxscores de la competición entera (más de un segundo en 3ª FEB), así que se reutilizan
# durante unos minutos en vez de repetir ese trabajo en cada consulta del mercado.
_PRICED_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
PRICED_TTL = 300.0  # segundos


# Cuánto pesa el +/- EN SU CONTEXTO. Un +/- suelto engaña: en un equipo que gana de 30
# todos acaban en positivo, y en uno que pierde de 20 todos en negativo. Lo que dice algo
# es la diferencia con lo que "tocaba" según el marcador y los minutos jugados.
PM_WEIGHT = 0.30      # puntos por cada unidad de impacto
PM_CAP = 15.0         # tope del impacto por partido (±4.5 puntos)
PM_MIN_FULL = 12.0    # minutos a partir de los cuales el impacto cuenta entero


def _pm_bonus(game: dict) -> float:
    """Ajuste por el +/- relativo al marcador y prorrateado por minutos.

    Si su equipo gana de 30 y él juega media hora, lo normal es acabar cerca de +22:
    quedarse en +1 es malo aunque el equipo arrase. Y al revés, aguantar en +13 mientras
    el equipo pierde es una actuación enorme que el marcador tapa.

    A quien juega poco se le pesa menos: dos minutos de basura no dicen nada.
    """
    mins = float(game.get("min") or 0.0)
    if mins <= 0:
        return 0.0
    esperado = float(game.get("margin") or 0) * (mins / 40.0)
    impacto = _clamp(float(game["pm"]) - esperado, -PM_CAP, PM_CAP)
    return round(PM_WEIGHT * impacto * min(1.0, mins / PM_MIN_FULL), 2)


def _fp(game: dict, win_bonus: float) -> float:
    """Puntos fantasy de UN partido: valoración + bonus por victoria + su +/- en pista."""
    return game["val"] + (win_bonus if game["won"] else 0.0) + _pm_bonus(game)


def all_priced(session: Session, league: FantasyLeague) -> list[dict]:
    """Todos los jugadores de la conferencia con precio actual y stats.

    `fp_avg`/`fp_form` son los PUNTOS FANTASY (lo que de verdad suma en la liga:
    valoración + win_bonus si su equipo ganó), y por eso el `win_bonus` entra en la
    clave de caché: dos ligas de la misma conferencia pueden premiar la victoria
    distinto y no deben compartir estos números.
    """
    key = (league.season, league.competition, league.grupo, league.current_jornada,
           league.win_bonus)
    hit = _PRICED_CACHE.get(key)
    if hit is not None and time.monotonic() - hit[0] < PRICED_TTL:
        # copia: quien llama trabaja con estos dicts y no debe poder tocar la caché
        return [dict(r) for r in hit[1]]

    conf = conference_games(session, league.competition, league.grupo, league.season)
    team_games: dict[int, int] = {}
    for d in conf.values():
        tg = len([g for g in d["games"] if g["j"] <= league.current_jornada])
        team_games[d["team_id"]] = max(team_games.get(d["team_id"], 0), tg)
    prev = season_prices(session, previous_season(league.season))
    fuera = departed_players(session, league.competition, league.grupo, league.season)
    rows = []
    for d in conf.values():
        played = [g for g in d["games"] if g["j"] <= league.current_jornada]
        if not played:
            continue
        n = len(played)
        price = _price_from_games(d["games"], league.current_jornada, team_games.get(d["team_id"], 1))
        prev_price = prev.get(d["player_id"])
        if prev_price is not None and n < BLEND_GAMES:
            # Arranque de temporada: pesa lo del año pasado hasta acumular partidos nuevos.
            w = n / BLEND_GAMES
            price = round(_clamp(w * price + (1 - w) * prev_price, PRICE_MIN, PRICE_MAX), 1)
        rows.append({
            "player_id": d["player_id"], "name": d["name"], "feb_code": d["feb_code"],
            "team_id": d["team_id"], "team": d["team"], "games": n,
            "price": price, "price_prev": prev_price,
            # se ha ido de la conferencia: ya no puntúa aunque siga en la plantilla
            "departed": d["player_id"] in fuera,
            "last_j": d.get("last_j", 0),
            "val_avg": round(sum(g["val"] for g in played) / n, 1),
            "pm_avg": round(sum(g["pm"] for g in played) / n, 1),
            "form": round(sum(g["val"] for g in played[-RECENT_N:]) / len(played[-RECENT_N:]), 1),
            # puntos fantasy: lo mismo que suma jornada_points(), pero en media
            "fp_avg": round(sum(_fp(g, league.win_bonus) for g in played) / n, 1),
            "fp_form": round(sum(_fp(g, league.win_bonus) for g in played[-RECENT_N:])
                             / len(played[-RECENT_N:]), 1),
            "wins": sum(1 for g in played if g["won"]),
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    _PRICED_CACHE[key] = (time.monotonic(), rows)
    return [dict(r) for r in rows]


def price_map(session: Session, league: FantasyLeague) -> dict[int, float]:
    return {r["player_id"]: r["price"] for r in all_priced(session, league)}


def listed_player_ids(session: Session, league: FantasyLeague) -> set[int]:
    """Jugadores que están AHORA MISMO en la subasta abierta.

    No tienen dueño todavía, pero están comprometidos: repartirlos por otra vía deja al
    mismo jugador en una plantilla y en el mercado a la vez.
    """
    rows = session.exec(select(FantasyListing).where(
        FantasyListing.league_id == league.id,
        FantasyListing.round_no == league.market_round,
        FantasyListing.resolved == False)).all()  # noqa: E712
    return {l.player_id for l in rows}


def owned_player_ids(session: Session, league_id: int) -> set[int]:
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league_id)).all()
    mids = [m.id for m in members]
    if not mids:
        return set()
    picks = session.exec(select(FantasyPick).where(FantasyPick.member_id.in_(mids))).all()
    return {p.player_id for p in picks}


# ============================ calendario de la jornada ============================
def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """Una hora peninsular de ese día, en UTC naive."""
    local = datetime(day.year, day.month, day.day, int(hour) % 24, minute, tzinfo=TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _weekly_slot(after: datetime, weekday: int, hour: int) -> datetime:
    """Siguiente <weekday> a las <hour> (hora peninsular) posterior a `after`, en UTC naive."""
    local = after.replace(tzinfo=timezone.utc).astimezone(TZ)
    cand = local.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    cand += timedelta(days=(int(weekday) % 7 - cand.weekday()) % 7)
    if cand <= local:
        cand += timedelta(days=7)
    return cand.astimezone(timezone.utc).replace(tzinfo=None)


MATCH_LEN_H = 3  # lo que se le da a un partido desde el salto para estar acabado


def dia_principal(dias: list[date]) -> Optional[date]:
    """El día en el que se juega la jornada: el que reúne a la mayoría.

    La FEB no dice si un partido se ha movido, así que se deduce comparando con este día.
    A igualdad de partidos gana el más temprano, que es el fin de semana de la jornada.
    """
    cuenta: dict[date, int] = {}
    for d in dias:
        if d:
            cuenta[d] = cuenta.get(d, 0) + 1
    return max(cuenta, key=lambda d: (cuenta[d], -d.toordinal())) if cuenta else None


def es_aplazado(day: Optional[date], principal: Optional[date]) -> bool:
    """Un partido está aplazado si se juega dos días o más después del grueso de la jornada."""
    return bool(day and principal and (day - principal).days >= 2)


def es_adelantado(day: Optional[date], principal: Optional[date]) -> bool:
    """Adelantado es dos días o más ANTES del grueso. Un partido que solo se juega unas
    horas antes el mismo fin de semana no es un adelanto: es la jornada, que se reparte."""
    return bool(day and principal and (day - principal).days <= -2)


def jornada_real_window(session: Session, league: FantasyLeague, jornada: int) -> tuple:
    """(primer salto, final) de una jornada según el calendario REAL de la FEB.

    Se prefiere `start_at` (fecha y hora exactas del partido, que es lo que la FEB publica
    mientras está por jugarse); si de un partido solo se sabe el día se usa la hora de
    partido de la liga. (None, None) si esa jornada no tiene calendario todavía.

    Los APLAZADOS no estiran el final: la jornada acaba cuando acaba su fin de semana,
    aunque quede un partido suelto tres semanas más tarde. Antes se esperaba a él y eso
    dejaba la liga entera parada (sin mercado y sin poder tocar el quinteto) todo ese
    tiempo; ahora la jornada se cierra a su hora y se puntúa provisional. Sí estiran el
    principio: en cuanto se juega el primer partido, aunque sea un adelantado, el quinteto
    tiene que estar cerrado.
    """
    q = select(Match.match_date, Match.start_at).where(Match.competition == league.competition,
                                                       Match.season == league.season,
                                                       Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    filas = session.exec(q).all()
    principal = dia_principal([day for day, _ in filas])
    starts, grueso, ends, ends_todos = [], [], [], []
    for day, start_at in filas:
        if start_at and day and day < start_at.date():
            # La FEB ha movido el DÍA hacia atrás pero no la hora: pasa con los adelantos
            # que publica tarde, porque al partido ya jugado le quita la hora y
            # `store_calendar` no la pisa con None. Manda el día, que es el dato fresco;
            # si mandara la hora vieja, la liga creería que la jornada no ha empezado y
            # se podría fichar a un jugador que ya ha puntuado.
            ini, fin = _at(day, league.play_hour), _at(day, 23, 59)
        elif start_at:
            ini, fin = start_at, start_at + timedelta(hours=MATCH_LEN_H)
        elif day:
            ini, fin = _at(day, league.play_hour), _at(day, 23, 59)
        else:
            continue
        starts.append(ini)
        ends_todos.append(fin)
        if not es_aplazado(day, principal):
            ends.append(fin)
        if not es_adelantado(day, principal):
            grueso.append(ini)
    if not starts:
        return (None, None, None)
    # Si TODA la jornada se ha movido no hay aplazados que valgan: es la jornada entera la
    # que cambia de fecha, y el final es el suyo nuevo.
    return min(starts), min(grueso or starts), max(ends or ends_todos)


def _first_kickoff(league: FantasyLeague, now: datetime) -> datetime:
    """Primer salto de la primera jornada de la liga: el próximo día de partido que deje
    tiempo de mercado por delante (si no, la liga nacería con el mercado ya cerrado)."""
    margin = timedelta(hours=league.market_close_before_h + 12)
    return _weekly_slot(now + margin, league.play_weekday, league.play_hour)


def jornada_window(session: Session, league: FantasyLeague, jornada: int) -> tuple:
    """(salto del grueso, final previsto) de una jornada, en UTC naive.

    Con la temporada en marcha manda el calendario real de la FEB. El "grueso" es el primer
    partido que NO va adelantado: es el que cierra el mercado, porque un partido que se
    juega dos días antes no debe robarle a toda la liga la semana de fichajes. Quien manda
    sobre el quinteto de los que ya han jugado es `sellar_quinteto`, no este reloj.
    En simulación —o si esa jornada no tiene fechas— manda el calendario semanal de la liga.
    """
    if not league.sim_mode:
        _, grueso, last = jornada_real_window(session, league, jornada)
        if grueso:
            return grueso, last
    start = league.kickoff_at or _first_kickoff(league, utcnow())
    return start, start + timedelta(hours=league.play_duration_h)


def primer_salto(session: Session, league: FantasyLeague, jornada: int) -> Optional[datetime]:
    """El primer partido de la jornada, adelantados incluidos. A partir de aquí ya hay
    puntos sobre la mesa y empieza a sellarse el quinteto, jugador a jugador."""
    if league.sim_mode:
        return None
    primero, _, _ = jornada_real_window(session, league, jornada)
    return primero


# Fases de la liga. El orden importa: es el ciclo por el que pasa cada jornada.
PHASES = ("mercado", "alineacion", "jornada", "fin")


def league_state(session: Session, league: FantasyLeague) -> dict:
    """En qué momento de la jornada está la liga, y hasta cuándo.

    Es la única fuente de verdad de lo que se puede y no se puede hacer: el mercado, las
    cláusulas, las ventas y el quinteto miran aquí antes de dejar tocar nada.
    """
    now = utcnow()
    nxt = league.current_jornada + 1
    if league.current_jornada >= league.max_jornada:
        return {"phase": "fin", "jornada": league.current_jornada, "kickoff_at": None,
                "ends_at": None, "market_deadline": None, "until": None, "pending": []}

    if league.sim_mode:
        # El reloj artificial se queda para el adorno: quien manda es el dueño de la liga.
        paso = sim_step_de(session, league)
        total = len(sim_partidos(session, league, nxt))
        sim = {"step": paso, "played": league.sim_played, "total": total}
        if paso == 0:
            # Con un adelantado, ese partido ya se ha disputado aunque el mercado siga
            # abierto: es exactamente la situación de un adelanto en la vida real.
            ade, _ = sim_reparto(session, league, nxt)
            return {"phase": "mercado", "jornada": nxt, "kickoff_at": None, "ends_at": None,
                    "market_deadline": None, "until": None,
                    "pending": sim_pendientes(session, league, nxt) if ade else [],
                    "adelanto": bool(ade), "sim": sim}
        return {"phase": "jornada", "jornada": nxt, "kickoff_at": None, "ends_at": None,
                "market_deadline": None, "until": None,
                "pending": sim_pendientes(session, league, nxt), "sim": sim}

    kickoff, ends = jornada_window(session, league, nxt)
    deadline = kickoff - timedelta(hours=league.market_close_before_h)
    pending: list[str] = []
    # ¿Se ha adelantado algún partido? Entonces hay puntos sobre la mesa antes de que la
    # jornada empiece de verdad. Se detecta por el reloj (el primer salto es anterior al
    # grueso) y también porque YA haya un resultado: eso último es la red que no depende
    # de que la FEB publique bien las horas, que a veces las publica tarde o no las
    # publica. En simulación no aplica: la base tiene todos los resultados desde el
    # principio y esto dispararía siempre.
    primero = primer_salto(session, league, nxt)
    hay_adelanto = bool(
        (primero and primero < kickoff and now >= primero)
        or jornada_empezada(session, league, nxt))

    if now >= kickoff:
        # `pending` es informativo: son los partidos de la jornada que aún no se han
        # disputado. Ya no alarga la fase (un aplazado tenía la liga parada semanas); lo
        # que hace es que la jornada se puntúe provisional y se complete después.
        phase, until = "jornada", ends
        pending = pending_matches(session, league, nxt)
    elif now < deadline:
        phase, until = "mercado", deadline
    else:
        phase, until = "alineacion", kickoff
    # Un adelanto NO cambia de fase: la liga sigue su semana igual. Lo único que queda
    # cerrado son los jugadores que ya han jugado, y de eso se encarga `sellar_quinteto`.
    # La bandera es para poder avisar: "ojo, este partido ya se juega".
    return {"phase": phase, "jornada": nxt, "kickoff_at": kickoff, "ends_at": ends,
            "market_deadline": deadline, "until": until, "pending": pending,
            "first_kickoff": primero, "adelanto": hay_adelanto}


def _phase_error(state: dict, what: str) -> str:
    j = state["jornada"]
    if state["phase"] == "fin":
        return "La temporada ya está completa"
    if state["phase"] == "alineacion":
        return (f"El mercado está cerrado: la jornada {j} está a punto de empezar. "
                f"Hasta el primer partido solo puedes cambiar el quinteto.")
    return (f"La jornada {j} se está jugando: {what} cuando termine."
            + (f" Falta por disputarse {state['pending'][0]}." if state["pending"] else ""))


def _require(session: Session, league: FantasyLeague, *allowed: str, what: str) -> dict:
    state = league_state(session, league)
    if state["phase"] not in allowed:
        raise ValueError(_phase_error(state, what))
    return state


# ============================ horario del mercado ============================
def _next_slot(after: datetime, weekday: int, hour: int) -> datetime:
    """Siguiente apertura del mercado (hora peninsular) tras `after`, en UTC naive.

    El mercado abre TODOS los días a la hora `hour` (el parámetro `weekday` se ignora,
    se mantiene por compatibilidad de firma). Antes abría un solo día a la semana."""
    local = after.replace(tzinfo=timezone.utc).astimezone(TZ)
    cand = local.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    if cand <= local:
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc).replace(tzinfo=None)


def _schedule_next_open(league: FantasyLeague, state: dict, after: datetime) -> None:
    """Programa la próxima apertura: la tanda diaria siguiente si aún cabe entera antes del
    corte de la jornada, y si no la primera de después de que se juegue."""
    nxt = _next_slot(after, league.market_weekday, league.market_hour)
    if state["market_deadline"] and nxt >= state["market_deadline"]:
        nxt = (_next_slot(state["ends_at"], league.market_weekday, league.market_hour)
               if state["ends_at"] else None)
    league.market_opens_at = nxt
    league.market_closes_at = None


_PARTICLES = {"de", "del", "la", "las", "los", "van", "der", "den", "da", "dos", "y", "i"}


def _nice(name: Optional[str]) -> str:
    """'A. PRIOR RUIZ' -> 'A. Prior Ruiz'. La FEB manda los nombres a gritos."""
    raw = (name or "").split(",")[0].strip()
    out = []
    for i, w in enumerate(raw.lower().split()):
        if w.endswith(".") or len(w) == 1:
            out.append(w.upper())
        elif i and w in _PARTICLES:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) or "?"


def _log(session: Session, league_id: int, kind: str, text: str) -> None:
    session.add(FantasyEvent(league_id=league_id, kind=kind, text=text))



def _notify(session: Session, league: FantasyLeague, member, kind: str,
            title: str, body: str = "") -> None:
    """Aviso personal para un mánager (acepta el FantasyMember o su id)."""
    m = member if isinstance(member, FantasyMember) else session.get(FantasyMember, member)
    if not m:
        return
    session.add(FantasyNotification(league_id=league.id, member_id=m.id, user_id=m.user_id,
                                    kind=kind, title=title, body=body))


def _members(session: Session, league_id: int) -> list[FantasyMember]:
    return session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league_id)).all()


def _open_round(session: Session, league: FantasyLeague, now: datetime,
                deadline: Optional[datetime] = None) -> bool:
    """Saca una tanda aleatoria de jugadores libres, repartida por tramos de precio.

    `deadline` es el cierre del mercado de la jornada: una tanda nunca puede acabar más
    tarde (si no, se estaría fichando con la jornada ya empezada)."""
    owned = owned_player_ids(session, league.id)
    pool = [r for r in all_priced(session, league) if r["player_id"] not in owned]
    if not pool:
        return False
    rng = random.Random(f"{league.id}:{league.market_round + 1}:{league.season}")
    pool.sort(key=lambda r: r["price"], reverse=True)
    n = min(league.market_size, len(pool))
    # tramos: 20% estrellas, 50% medios, 30% chollos → mercado variado y entretenido
    cut1, cut2 = max(1, len(pool) // 5), max(2, len(pool) // 2)
    tiers = [pool[:cut1], pool[cut1:cut2], pool[cut2:]]
    want = [max(1, round(n * 0.2)), max(1, round(n * 0.5)), max(1, round(n * 0.3))]
    chosen: list[dict] = []
    for tier, k in zip(tiers, want):
        if tier:
            chosen += rng.sample(tier, min(k, len(tier)))
    rest = [r for r in pool if r not in chosen]
    if len(chosen) < n and rest:
        chosen += rng.sample(rest, min(n - len(chosen), len(rest)))
    rng.shuffle(chosen)

    league.market_round += 1
    league.market_open = True
    league.market_opens_at = now
    # La tanda dura hasta la hora de mercado del día siguiente (así el relevo cae siempre a
    # la misma hora, aunque la tanda anterior empezara a deshoras), y nunca más allá del corte.
    closes = min(now + timedelta(hours=league.market_duration_h),
                 _next_slot(now, league.market_weekday, league.market_hour))
    league.market_closes_at = min(closes, deadline) if deadline else closes
    for r in chosen[:n]:
        session.add(FantasyListing(league_id=league.id, round_no=league.market_round,
                                   player_id=r["player_id"], price=r["price"]))
    _log(session, league.id, "market",
         f"🟢 Mercado abierto · {len(chosen[:n])} jugadores a subasta (tanda {league.market_round})")
    for m in _members(session, league.id):
        _notify(session, league, m, "market", "Mercado abierto",
                f"{len(chosen[:n])} jugadores a subasta durante {league.market_duration_h} h")
    session.add(league)
    return True


def _resolve_round(session: Session, league: FantasyLeague) -> None:
    """Cierra la tanda: cada jugador va a la puja más alta (a igualdad, la primera)."""
    listings = session.exec(select(FantasyListing).where(
        FantasyListing.league_id == league.id,
        FantasyListing.round_no == league.market_round,
        FantasyListing.resolved == False)).all()  # noqa: E712
    sold = 0
    for lst in listings:
        bids = session.exec(select(FantasyBid).where(
            FantasyBid.listing_id == lst.id, FantasyBid.status == "active")).all()
        bids.sort(key=lambda b: (-b.amount, b.created_at))
        winner = None
        for b in bids:
            m = session.get(FantasyMember, b.member_id)
            picks = picks_of(session, m.id)
            if not m or b.amount > m.budget_remaining + 1e-6 or len(picks) >= league.squad_size:
                b.status = "lost"
                session.add(b)
                continue
            winner = (b, m)
            break
        for b in bids:
            if winner and b.id == winner[0].id:
                continue
            if b.status == "active":
                b.status = "lost"
                session.add(b)
        pl_row = session.get(Player, lst.player_id)
        pl_name = _nice(pl_row.name if pl_row else None)
        # Cinturón y tirantes: si a estas alturas el jugador ya tiene dueño (por la vía
        # que sea), la subasta se anula entera. Nadie paga y nadie se lo lleva; sería
        # mucho peor acabar con el mismo jugador en dos plantillas.
        if lst.player_id in owned_player_ids(session, league.id):
            for b in bids:
                b.status = "lost"
                session.add(b)
            lst.resolved = True
            session.add(lst)
            print(f"[mercado] subasta anulada: {pl_name} ya tenía dueño", flush=True)
            continue
        if winner:
            b, m = winner
            b.status = "won"
            m.budget_remaining = round(m.budget_remaining - b.amount, 1)
            starters = sum(1 for p in picks_of(session, m.id) if p.starter)
            _new_pick(session, league, m, lst.player_id, b.amount, lst.price,
                      starters < league.lineup_size)
            lst.winner_member_id = m.id
            lst.sold_price = b.amount
            sold += 1
            _log(session, league.id, "signing",
                 f"✍️ {m.manager_name} ficha a {pl_name} por {b.amount} M€")
            _notify(session, league, m, "signing", f"Has fichado a {pl_name}",
                    f"Tu puja de {b.amount} M€ fue la más alta")
            session.add_all([b, m])
        # a los que se quedaron a las puertas también hay que contárselo
        for b in bids:
            if winner and b.id == winner[0].id:
                continue
            _notify(session, league, b.member_id, "outbid", f"Te has quedado sin {pl_name}",
                    f"Se lo llevó {winner[1].manager_name} por {winner[0].amount} M€"
                    if winner else "Nadie pudo cerrar el fichaje")
        lst.resolved = True
        session.add(lst)
    league.market_open = False
    _log(session, league.id, "market", f"🔴 Mercado cerrado · {sold} fichajes")
    session.add(league)


def sync_market(session: Session, league: FantasyLeague) -> FantasyLeague:
    """Pone la liga en el estado que le toca por reloj. Idempotente y perezoso.

    Hace tres cosas, en este orden: cerrar el mercado en cuanto se entra en la recta final
    de la jornada, puntuar la jornada cuando ya se ha jugado entera, y abrir/cerrar las
    tandas diarias mientras el mercado esté en fase de mercado.
    """
    changed = False
    # Lo primero: rematar las jornadas que se puntuaron a medias, por si mientras tanto se
    # ha jugado el partido que faltaba (es el cron horario quien trae el resultado).
    if completar(session, league):
        changed = True
    if league.kickoff_at is None and league.current_jornada < league.max_jornada:
        # Liga creada antes de que existiera el calendario (o en modo real sin fechas).
        league.kickoff_at = _first_kickoff(league, utcnow())
        session.add(league)
        changed = True

    for _ in range(12):  # guarda contra bucles
        now = utcnow()
        state = league_state(session, league)
        phase = state["phase"]

        # Fuera de la fase de mercado no puede quedar ninguna subasta viva.
        if phase != "mercado" and league.market_open:
            _resolve_round(session, league)
            _schedule_next_open(league, state, state["ends_at"] or now)
            changed = True
            continue

        if state.get("adelanto") and phase != "jornada":
            # Hay un partido por delante del resto: se cierran SOLO sus jugadores. La liga
            # sigue su semana con normalidad, que es la gracia.
            sellar_quinteto(session, league, state["jornada"])

        if phase == "jornada":
            # Ya ha saltado el grueso: se cierra todo lo que quede por sellar.
            freeze_lineups(session, league, state["jornada"])
            # Pasada su hora, se puntúa sola. Ya no se espera a los aplazados: la jornada
            # se cierra con lo jugado y `completar()` sube después lo que falte.
            # En simulación por pasos no hay reloj (`ends_at` es None): la jornada
            # la cierra el dueño con el tercer paso, aquí no se avanza sola.
            if state["ends_at"] is not None and now >= state["ends_at"] \
                    and advance(session, league).get("ok"):
                changed = True
                continue
            break

        if phase == "mercado":
            # Sin hora de cierre la tanda se quedaría abierta para siempre: se cierra ya.
            if league.market_open and (league.market_closes_at is None
                                       or now >= league.market_closes_at):
                _resolve_round(session, league)
                # Relevo inmediato: mientras dure la fase de mercado siempre hay subastas
                # vivas; lo que cambia cada día es la tanda de jugadores.
                league.market_opens_at, league.market_closes_at = now, None
                changed = True
                continue
            if not league.market_open and (league.market_opens_at is None
                                           or now >= league.market_opens_at):
                # Una tanda de diez minutos no la juega nadie: si ya no cabe antes del
                # corte, se espera a la ventana de mercado de la jornada siguiente.
                # Sin corte de mercado (simulación por pasos) siempre cabe otra tanda.
                corte = state["market_deadline"]
                if (corte is None or corte - now >= timedelta(hours=1)) \
                        and _open_round(session, league, now, corte):
                    changed = True
                    continue
                league.market_opens_at = (_next_slot(state["ends_at"], league.market_weekday,
                                                     league.market_hour)
                                          if state["ends_at"] else None)
                session.add(league)
                changed = True
                continue
        break

    if changed:
        session.commit()
        session.refresh(league)
    return league


# ============================ puntuación por jornada ============================
# ============================ simulación paso a paso ============================
# En simulación el reloj no significa nada: la temporada de la base ya está jugada entera.
# Antes eso hacía que un clic saltara la jornada completa. Ahora el dueño la mueve en tres
# pasos, como un fin de semana de verdad: viernes noche se cierra todo, el sábado se van
# jugando partidos y se puede ir mirando, y el domingo se cierra la jornada.

def _sim_base(session: Session, league: FantasyLeague, jornada: int) -> list[int]:
    """Los partidos de una jornada en su orden natural, sin incidencias."""
    q = select(Match.id).where(Match.competition == league.competition,
                               Match.season == league.season,
                               Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    # por fecha y luego por id: el mismo orden en cada llamada, que si no "los primeros
    # tres partidos" serían tres distintos cada vez que se mira
    q = q.order_by(Match.match_date, Match.id)
    return list(session.exec(q).all())


# Cada cuánto le toca a una jornada un partido movido. Un tercio y un cuarto es más de lo
# que pasa de verdad, pero la gracia de la simulación es que se vea: con los de la FEB
# (dos o tres por temporada) habría que jugar meses para toparse con uno.
SIM_P_ADELANTO = 0.34
SIM_P_APLAZADO = 0.25


def sim_reparto(session: Session, league: FantasyLeague,
                jornada: int) -> tuple[Optional[int], Optional[int]]:
    """(partido adelantado, partido aplazado) de esa jornada en simulación.

    Determinista: la misma liga y la misma jornada dan siempre lo mismo, aunque se
    recargue la pantalla mil veces. La temporada ya jugada no trae estas situaciones (ver
    `FantasyLeague.sim_incidencias`), así que aquí se inventan para poder verlas.
    """
    if not (league.sim_mode and league.sim_incidencias):
        return None, None
    ids = _sim_base(session, league, jornada)
    if len(ids) < 3:
        return None, None       # con dos partidos, mover uno es media jornada
    rng = random.Random(f"{league.id}:{jornada}:incidencias")
    ade = ids[rng.randrange(len(ids))] if rng.random() < SIM_P_ADELANTO else None
    resto = [x for x in ids if x != ade]
    apl = resto[rng.randrange(len(resto))] if rng.random() < SIM_P_APLAZADO else None
    return ade, apl


def sim_partidos(session: Session, league: FantasyLeague, jornada: int) -> list[int]:
    """Los partidos de una jornada, en el orden en que se van a ir disputando.

    El adelantado va primero (se juega antes de que cierre el mercado) y el aplazado el
    último (se queda sin disputar cuando la jornada se cierra). Así el resto del ciclo
    —que solo mira "cuántos llevo jugados"— sale bien sin saber nada de incidencias.
    """
    ids = _sim_base(session, league, jornada)
    ade, apl = sim_reparto(session, league, jornada)
    if not ade and not apl:
        return ids
    medio = [x for x in ids if x not in (ade, apl)]
    return ([ade] if ade else []) + medio + ([apl] if apl else [])


def _nombre_partido(session: Session, m: Match) -> str:
    local = session.get(Team, m.home_team_id) if m.home_team_id else None
    visit = session.get(Team, m.away_team_id) if m.away_team_id else None
    return f"{local.name if local else '?'} - {visit.name if visit else '?'}"


def _aplazados_sim(league: FantasyLeague) -> dict[int, int]:
    """{jornada: match_id} de los aplazados que aún no se han disputado."""
    try:
        return {int(k): int(v) for k, v in json.loads(league.sim_aplazados or "{}").items()}
    except (TypeError, ValueError):
        return {}


def _guardar_aplazados(league: FantasyLeague, d: dict[int, int]) -> None:
    league.sim_aplazados = json.dumps({str(k): v for k, v in d.items()}) if d else None


def sim_step_de(session: Session, league: FantasyLeague) -> int:
    """0 = mercado, 1 = jornada en juego. Se deduce del reloj la primera vez.

    Las ligas creadas antes de esto no tienen paso guardado, y ponerlas todas en "mercado"
    las sacaría de golpe de una jornada que están jugando. Así que la primera vez se mira
    el reloj viejo y se escribe lo que dijera.
    """
    if league.sim_step is not None:
        return league.sim_step
    nxt = league.current_jornada + 1
    kickoff, _ = jornada_window(session, league, nxt)
    league.sim_step = 1 if utcnow() >= kickoff else 0
    if league.sim_step == 1:
        # estaba jugándose: se da por disputada entera, que es lo que el reloj decía
        league.sim_played = len(sim_partidos(session, league, nxt))
    session.add(league)
    session.commit()
    return league.sim_step


def sim_jugados(session: Session, league: FantasyLeague, jornada: int) -> Optional[set[int]]:
    """Partidos que YA se han disputado de una jornada, o None si cuentan todos.

    Recorta la jornada en curso y también las pasadas a las que les quedara un aplazado:
    esas se puntuaron en provisional y no cuentan enteras hasta que se dispute.
    """
    if not league.sim_mode:
        return None
    if jornada == league.current_jornada + 1:
        if sim_step_de(session, league) == 0:
            # Aún no ha empezado la jornada… salvo el adelantado, que se juega antes de
            # que cierre el mercado: es la gracia de un adelanto.
            ade, _ = sim_reparto(session, league, jornada)
            return {ade} if ade else set()
        return set(sim_partidos(session, league, jornada)[:league.sim_played])
    pendiente = _aplazados_sim(league).get(jornada)
    if pendiente:
        return set(sim_partidos(session, league, jornada)) - {pendiente}
    return None


def jornada_points(session: Session, league: FantasyLeague, jornada: int) -> dict[int, float]:
    conf = conference_games(session, league.competition, league.grupo, league.season)
    jugados = sim_jugados(session, league, jornada)
    out: dict[int, float] = {}
    for pid, d in conf.items():
        games = [g for g in d["games"] if g["j"] == jornada
                 and (jugados is None or g["mid"] in jugados)]
        if games:
            out[pid] = round(sum(_fp(g, league.win_bonus) for g in games), 1)
    return out


# ============================ ligas ============================
def _code(session: Session) -> str:
    while True:
        c = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not session.exec(select(FantasyLeague).where(FantasyLeague.join_code == c)).first():
            return c


def create_league(session: Session, owner_id: int, name: str, competition: str,
                  grupo: Optional[str], season: str, manager_name: str,
                  budget: float = 100.0, squad_size: int = 10, lineup_size: int = 5,
                  win_bonus: float = 4.0, start_jornada: Optional[int] = None,
                  market_weekday: int = 4, market_hour: int = 20,
                  market_duration_h: int = 24, market_size: int = 15,
                  initial_squad: int = 5, clause_factor: float = 2.0,
                  clause_lock_h: int = 24, open_now: bool = True,
                  sim_mode: Optional[bool] = None, sim_incidencias: bool = False,
                  play_weekday: int = 5, play_hour: int = 18,
                  play_duration_h: int = 30,
                  market_close_before_h: int = 19) -> FantasyLeague:
    if competition not in FANTASY_COMPETITIONS:
        raise ValueError("Esa competición no está disponible para el fantasy.")
    prog = season_progress(session, competition, grupo, season)
    mj = prog["max_jornada"]
    if mj == 0:
        raise ValueError("Esa conferencia no tiene datos de partidos todavía")
    # Con la temporada en marcha se juega contra el calendario real y se arranca donde
    # esté de verdad; si ya está entera, se repite en simulación desde media temporada.
    if sim_mode is None:
        sim_mode = not prog["live"]
    if start_jornada is not None:
        start = start_jornada
    elif sim_mode:
        start = max(3, round(mj * 0.35))
    else:
        start = prog["last_played"]
    if not sim_mode and prog["last_played"] == 0:
        raise ValueError("La temporada aún no ha empezado: espera a que se juegue la "
                         "primera jornada (antes no hay ni plantillas ni precios).")
    start = int(_clamp(start, 1, mj - 1))
    now = utcnow()
    league = FantasyLeague(
        name=name, join_code=_code(session), owner_user_id=owner_id, season=season,
        competition=competition, grupo=grupo, budget=budget, squad_size=squad_size,
        lineup_size=lineup_size, initial_squad=initial_squad, win_bonus=win_bonus,
        start_jornada=start, current_jornada=start, max_jornada=mj,
        market_weekday=int(_clamp(market_weekday, 0, 6)), market_hour=int(_clamp(market_hour, 0, 23)),
        market_duration_h=int(_clamp(market_duration_h, 1, 168)),
        market_size=int(_clamp(market_size, 4, 30)),
        clause_factor=float(_clamp(clause_factor, 1.2, 5.0)),
        clause_lock_h=int(_clamp(clause_lock_h, 0, 168)),
        sim_mode=bool(sim_mode), sim_incidencias=bool(sim_incidencias),
        play_weekday=int(_clamp(play_weekday, 0, 6)), play_hour=int(_clamp(play_hour, 0, 23)),
        play_duration_h=int(_clamp(play_duration_h, 2, 168)),
        market_close_before_h=int(_clamp(market_close_before_h, 0, 120)),
        # el primer mercado abre ya (para poder jugar desde el minuto uno); los siguientes
        # siguen el horario elegido
        market_opens_at=now if open_now else _next_slot(now, market_weekday, market_hour),
    )
    league.kickoff_at = _first_kickoff(league, now)
    session.add(league)
    session.commit()
    session.refresh(league)
    cuando = (f"jornada los {WEEKDAYS[league.play_weekday]} a las {league.play_hour:02d}:00"
              if league.sim_mode else "calendario real de la FEB")
    _log(session, league.id, "info",
         f"🏆 Liga creada · {cuando} · mercado todos los días a las "
         f"{league.market_hour:02d}:00 hasta {league.market_close_before_h} h antes")
    session.commit()
    join_league(session, league, owner_id, manager_name)
    sync_market(session, league)
    return league


def _assign_initial_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> None:
    """Plantilla inicial aleatoria para poder jugar desde el primer momento."""
    if league.initial_squad <= 0:
        return
    # Fuera los que ya tienen dueño Y los que están en la subasta abierta: si entras en
    # la liga con el mercado en marcha, te podía tocar de regalo un jugador por el que
    # los demás están pujando en ese mismo momento.
    fuera = owned_player_ids(session, league.id) | listed_player_ids(session, league)
    pool = [r for r in all_priced(session, league) if r["player_id"] not in fuera]
    if not pool:
        return
    rng = random.Random(f"{league.id}:init:{member.id}")
    budget_cap = league.budget * 0.45
    rng.shuffle(pool)
    spent = 0.0
    for r in pool:
        if sum(1 for _ in picks_of(session, member.id)) >= league.initial_squad:
            break
        if spent + r["price"] > budget_cap:
            continue
        starters = sum(1 for p in picks_of(session, member.id) if p.starter)
        _new_pick(session, league, member, r["player_id"], r["price"], r["price"],
                  starters < league.lineup_size)
        spent += r["price"]
        session.commit()
    member.budget_remaining = round(member.budget_remaining - spent, 1)
    session.add(member)
    session.commit()


def join_league(session: Session, league: FantasyLeague, user_id: int, manager_name: str) -> FantasyMember:
    existing = session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league.id, FantasyMember.user_id == user_id)).first()
    if existing:
        return existing
    m = FantasyMember(league_id=league.id, user_id=user_id, manager_name=manager_name,
                      budget_remaining=league.budget)
    session.add(m)
    session.commit()
    session.refresh(m)
    _assign_initial_squad(session, league, m)
    _log(session, league.id, "join", f"👋 {manager_name} se une a la liga")
    for other in _members(session, league.id):
        if other.id != m.id:
            _notify(session, league, other, "join", f"{manager_name} se une a la liga",
                    f"Ya sois {len(_members(session, league.id))} mánagers")
    session.commit()
    return m


def member_of(session: Session, league_id: int, user_id: int) -> Optional[FantasyMember]:
    return session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league_id, FantasyMember.user_id == user_id)).first()


def picks_of(session: Session, member_id: int) -> list[FantasyPick]:
    return session.exec(select(FantasyPick).where(FantasyPick.member_id == member_id)).all()


# ============================ mercado / pujas ============================
def market(session: Session, league: FantasyLeague, member: Optional[FantasyMember]) -> dict:
    """Subastas abiertas de la tanda actual, con info de mis pujas."""
    sync_market(session, league)
    listings = session.exec(select(FantasyListing).where(
        FantasyListing.league_id == league.id,
        FantasyListing.round_no == league.market_round,
        FantasyListing.resolved == False)).all()  # noqa: E712
    info = {r["player_id"]: r for r in all_priced(session, league)}
    my_bids = {}
    if member:
        for b in session.exec(select(FantasyBid).where(
                FantasyBid.member_id == member.id, FantasyBid.status == "active")).all():
            my_bids[b.listing_id] = b
    rows = []
    for lst in listings:
        d = info.get(lst.player_id, {})
        n_bids = len(session.exec(select(FantasyBid).where(
            FantasyBid.listing_id == lst.id, FantasyBid.status == "active")).all())
        mine = my_bids.get(lst.id)
        rows.append({
            "listing_id": lst.id, "player_id": lst.player_id,
            "name": d.get("name", "?"), "feb_code": d.get("feb_code"), "team": d.get("team"),
            "price": lst.price, "val_avg": d.get("val_avg", 0), "pm_avg": d.get("pm_avg", 0),
            "form": d.get("form", 0), "bids": n_bids,
            "fp_avg": d.get("fp_avg", 0), "fp_form": d.get("fp_form", 0),
            "games": d.get("games", 0),
            "my_bid": mine.amount if mine else None,
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    state = league_state(session, league)
    return {
        "open": league.market_open,
        "round": league.market_round,
        "closes_at": _iso(league.market_closes_at),
        "opens_at": _iso(league.market_opens_at),
        "phase": state["phase"], "phase_until": _iso(state["until"]),
        "next_jornada": state["jornada"], "pending_matches": state["pending"],
        "listings": rows,
        "my_budget": member.budget_remaining if member else None,
        "committed": committed_amount(session, member.id) if member else 0.0,
    }


SALE_DAYS = 3          # días que dura el escaparate de una venta
SALE_MIN = -0.05       # la liga ofrece entre un 5% menos...
SALE_MAX = 0.10        # ...y un 10% más del valor de mercado


def committed_amount(session: Session, member_id: int) -> float:
    """Dinero apalabrado: pujas vivas y ofertas hechas a otros mánagers.

    Cuenta como gastado aunque todavía no lo esté: si no, se podría pujar y ofertar
    varias veces el mismo dinero y acabar debiendo más de lo que se tiene."""
    bids = session.exec(select(FantasyBid).where(
        FantasyBid.member_id == member_id, FantasyBid.status == "active")).all()
    ofertas = session.exec(select(FantasyOffer).where(
        FantasyOffer.from_member_id == member_id,
        FantasyOffer.status == "pending")).all()
    return round(sum(b.amount for b in bids) + sum(o.amount for o in ofertas), 1)


def place_bid(session: Session, league: FantasyLeague, member: FantasyMember,
              listing_id: int, amount: float) -> dict:
    sync_market(session, league)
    _require(session, league, "mercado", what="podrás volver a pujar")
    if not league.market_open:
        raise ValueError("El mercado está cerrado")
    lst = session.get(FantasyListing, listing_id)
    if not lst or lst.league_id != league.id or lst.resolved or lst.round_no != league.market_round:
        raise ValueError("Esa subasta ya no está disponible")
    if len(picks_of(session, member.id)) >= league.squad_size:
        raise ValueError(f"Plantilla llena ({league.squad_size} jugadores)")
    amount = round(float(amount), 1)
    if amount < lst.price:
        raise ValueError(f"La puja mínima es {lst.price} M€")
    prev = session.exec(select(FantasyBid).where(
        FantasyBid.listing_id == lst.id, FantasyBid.member_id == member.id,
        FantasyBid.status == "active")).first()
    other = committed_amount(session, member.id) - (prev.amount if prev else 0.0)
    if amount + other > member.budget_remaining + 1e-6:
        raise ValueError("No te llega el presupuesto con las pujas que ya tienes")
    if prev:
        prev.amount = amount
        session.add(prev)
    else:
        session.add(FantasyBid(league_id=league.id, listing_id=lst.id,
                               member_id=member.id, amount=amount))
    session.commit()
    return {"ok": True, "amount": amount}


def cancel_bid(session: Session, league: FantasyLeague, member: FantasyMember, listing_id: int) -> dict:
    bid = session.exec(select(FantasyBid).where(
        FantasyBid.listing_id == listing_id, FantasyBid.member_id == member.id,
        FantasyBid.status == "active")).first()
    if not bid:
        raise ValueError("No tienes una puja ahí")
    bid.status = "cancelled"
    session.add(bid)
    session.commit()
    return {"ok": True}


def close_market_now(session: Session, league: FantasyLeague) -> dict:
    """Cierra la tanda actual ya (para probar sin esperar al horario)."""
    sync_market(session, league)
    if not league.market_open:
        raise ValueError("El mercado ya está cerrado")
    _resolve_round(session, league)
    _schedule_next_open(league, league_state(session, league), utcnow())
    session.add(league)
    session.commit()
    session.refresh(league)
    return {"ok": True, "round": league.market_round}


def open_market_now(session: Session, league: FantasyLeague) -> dict:
    """Abre una tanda ya (para probar sin esperar al horario)."""
    sync_market(session, league)
    if league.market_open:
        raise ValueError("El mercado ya está abierto")
    state = _require(session, league, "mercado", what="volverá a haber mercado")
    _open_round(session, league, utcnow(), state["market_deadline"])
    session.commit()
    session.refresh(league)
    return {"ok": True, "round": league.market_round}


# ============================ cláusulas de rescisión ============================
def _clause_for(league: FantasyLeague, value: float) -> float:
    return round(max(value, PRICE_MIN) * league.clause_factor, 1)


def _new_pick(session: Session, league: FantasyLeague, member: FantasyMember,
              player_id: int, paid: float, value: float, starter: bool) -> FantasyPick:
    pick = FantasyPick(
        member_id=member.id, player_id=player_id, buy_price=paid,
        buy_jornada=league.current_jornada, starter=starter,
        clause=_clause_for(league, max(value, paid)),
        clause_locked_until=utcnow() + timedelta(hours=league.clause_lock_h),
    )
    session.add(pick)
    return pick


def pay_clause(session: Session, league: FantasyLeague, member: FantasyMember,
               player_id: int) -> dict:
    """Clausulazo: te llevas al jugador de otro mánager pagando su cláusula (el dinero
    va íntegro al dueño)."""
    sync_market(session, league)
    _require(session, league, "mercado", what="podrás ir de clausulazo")
    pick = session.exec(select(FantasyPick).join(
        FantasyMember, FantasyMember.id == FantasyPick.member_id).where(
        FantasyMember.league_id == league.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("Ese jugador no lo tiene nadie: ficha por el mercado")
    if pick.member_id == member.id:
        raise ValueError("Ese jugador ya es tuyo")
    if pick.clause_locked_until and utcnow() < pick.clause_locked_until:
        mins = int((pick.clause_locked_until - utcnow()).total_seconds() // 60)
        raise ValueError(f"Jugador blindado {mins // 60}h {mins % 60}m más")
    if len(picks_of(session, member.id)) >= league.squad_size:
        raise ValueError(f"Plantilla llena ({league.squad_size} jugadores)")
    amount = round(pick.clause, 1)
    free = member.budget_remaining - committed_amount(session, member.id)
    if amount > free + 1e-6:
        raise ValueError(f"Necesitas {amount} M€ libres (tienes {round(free, 1)})")

    owner = session.get(FantasyMember, pick.member_id)
    value = price_map(session, league).get(player_id, amount)
    member.budget_remaining = round(member.budget_remaining - amount, 1)
    owner.budget_remaining = round(owner.budget_remaining + amount, 1)
    starters = sum(1 for p in picks_of(session, member.id) if p.starter)
    session.delete(pick)
    _new_pick(session, league, member, player_id, amount, value, starters < league.lineup_size)
    session.add_all([member, owner])
    pl = session.get(Player, player_id)
    pl_name = _nice(pl.name if pl else None)
    _log(session, league.id, "clause",
         f"💥 CLAUSULAZO · {member.manager_name} se lleva a {pl_name} "
         f"de {owner.manager_name} por {amount} M€")
    _notify(session, league, owner, "clause", f"Te han clausulado a {pl_name}",
            f"{member.manager_name} ha pagado {amount} M€ · el dinero es tuyo")
    session.commit()
    return {"ok": True, "paid": amount, "budget_remaining": member.budget_remaining}


def raise_clause(session: Session, league: FantasyLeague, member: FantasyMember,
                 player_id: int, new_clause: float) -> dict:
    """Sube la cláusula de tu jugador. Cuesta un % de la subida."""
    sync_market(session, league)
    _require(session, league, "mercado", what="podrás blindarlo")
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    new_clause = round(float(new_clause), 1)
    if new_clause <= pick.clause:
        raise ValueError(f"La cláusula ya es de {pick.clause} M€")
    cost = round((new_clause - pick.clause) * league.clause_raise_cost, 1)
    free = member.budget_remaining - committed_amount(session, member.id)
    if cost > free + 1e-6:
        raise ValueError(f"Subirla cuesta {cost} M€ y solo tienes {round(free, 1)} libres")
    pick.clause = new_clause
    member.budget_remaining = round(member.budget_remaining - cost, 1)
    session.add_all([pick, member])
    session.commit()
    return {"ok": True, "clause": new_clause, "cost": cost,
            "budget_remaining": member.budget_remaining}


# ============================ ficha del jugador ============================
def player_jornada_line(session: Session, league: FantasyLeague, player_id: int,
                        jornada: int) -> Optional[dict]:
    """El partido de ese jugador en esa jornada, línea de acta completa.

    Es lo que uno quiere ver al mirar atrás una jornada: no su media de la temporada, sino
    qué hizo ESE día y de dónde salen sus puntos fantasy.
    """
    rows = session.exec(
        select(PlayerMatchStat, Match, Team)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(PlayerMatchStat.player_id == player_id, Team.season == league.season,
               Match.jornada_num == jornada)
    ).all()
    if not rows:
        return None
    st, m, team = rows[0]
    rival = session.get(Team, m.away_team_id if st.is_home else m.home_team_id)
    mine = m.home_score if st.is_home else m.away_score
    opp = m.away_score if st.is_home else m.home_score
    won = mine is not None and opp is not None and mine > opp
    g = {"val": st.val, "pm": st.plus_minus, "won": won,
         "min": round(st.seconds / 60.0, 1),
         "margin": (mine - opp) if (mine is not None and opp is not None) else 0}
    pm_bonus = _pm_bonus(g)
    return {
        "jornada": jornada, "team": team.name, "rival": rival.name if rival else None,
        "home": st.is_home, "score": f"{mine}-{opp}" if mine is not None else None,
        "won": won, "starter": st.starter,
        "min": round(st.seconds / 60), "pts": st.pts, "val": st.val, "pm": st.plus_minus,
        "t2": f"{st.t2m}/{st.t2a}", "t3": f"{st.t3m}/{st.t3a}", "tl": f"{st.tlm}/{st.tla}",
        "reb": st.treb, "oreb": st.oreb, "dreb": st.dreb, "ast": st.ast, "stl": st.stl,
        "blk": st.blk_for, "tov": st.tov, "pf": st.pf_committed,
        # el desglose de los puntos fantasy de esa jornada
        "win_bonus": league.win_bonus if won else 0.0,
        "pm_bonus": pm_bonus,
        "points": round(_fp(g, league.win_bonus), 1),
    }



def player_detail(session: Session, league: FantasyLeague, player_id: int,
                  jornada: Optional[int] = None) -> dict:
    """Estadísticas del jugador + su situación en la liga (dueño, cláusula).

    Solo cuentan las jornadas ya disputadas EN LA LIGA (`current_jornada`): la temporada
    de la base está entera, así que sin este corte la ficha destriparía partidos que en la
    liga todavía no se han jugado.
    """
    pl = session.get(Player, player_id)
    if not pl:
        raise ValueError("Jugador no encontrado")
    rows = session.exec(
        select(PlayerMatchStat, Match, Team)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(PlayerMatchStat.player_id == player_id, Team.season == league.season,
               Match.jornada_num != None,  # noqa: E711
               Match.jornada_num <= league.current_jornada)
    ).all()
    agg = {k: 0 for k in ("seconds", "pts", "val", "plus_minus", "treb", "oreb", "dreb", "ast",
                          "stl", "tov", "blk_for", "pf_committed", "t2m", "t2a", "t3m", "t3a",
                          "tlm", "tla")}
    games, team_name, wins = [], None, 0
    for st, m, tm in rows:
        team_name = tm.name
        for k in agg:
            agg[k] += getattr(st, k)
        my = m.home_score if st.is_home else m.away_score
        opp = m.away_score if st.is_home else m.home_score
        won = my is not None and opp is not None and my > opp
        wins += int(won)
        g = {"j": m.jornada_num, "val": st.val, "pts": st.pts, "reb": st.treb,
             "ast": st.ast, "pm": st.plus_minus, "min": round(st.seconds / 60, 1),
             "won": won, "margin": (my - opp) if (my is not None and opp is not None) else 0}
        # los puntos de ese partido ya calculados: la fórmula vive en un solo sitio
        g["pm_bonus"] = _pm_bonus(g)
        g["fp"] = round(_fp(g, league.win_bonus), 1)
        games.append(g)
    n = len(rows) or 1
    fga, fgm = agg["t2a"] + agg["t3a"], agg["t2m"] + agg["t3m"]
    ts_den = 2 * (fga + 0.44 * agg["tla"])
    games.sort(key=lambda g: g["j"] or 0)
    info = next((r for r in all_priced(session, league) if r["player_id"] == player_id), {})

    pick = session.exec(select(FantasyPick).join(
        FantasyMember, FantasyMember.id == FantasyPick.member_id).where(
        FantasyMember.league_id == league.id, FantasyPick.player_id == player_id)).first()
    owner = session.get(FantasyMember, pick.member_id) if pick else None
    locked = bool(pick and pick.clause_locked_until and utcnow() < pick.clause_locked_until)
    lock_mins = int((pick.clause_locked_until - utcnow()).total_seconds() // 60) if locked else 0

    return {
        "player_id": player_id, "name": pl.name, "feb_code": pl.feb_code, "team": team_name,
        "price": info.get("price"), "form": info.get("form"), "games": len(rows),
        "wins": wins, "losses": len(rows) - wins,
        # puntos fantasy (lo que suma en la liga) y el bonus con el que se calculan
        "fp_avg": info.get("fp_avg", 0), "fp_form": info.get("fp_form", 0),
        "win_bonus": league.win_bonus,
        # contra quién juega la próxima: lo primero que se mira antes de alinear
        "next_match": next_match_for_team(session, league, info.get("team_id")),
        "avg": {
            "min": round(agg["seconds"] / n / 60, 1), "pts": round(agg["pts"] / n, 1),
            "reb": round(agg["treb"] / n, 1), "oreb": round(agg["oreb"] / n, 1),
            "dreb": round(agg["dreb"] / n, 1), "ast": round(agg["ast"] / n, 1),
            "stl": round(agg["stl"] / n, 1), "tov": round(agg["tov"] / n, 1),
            "blk": round(agg["blk_for"] / n, 1), "pf": round(agg["pf_committed"] / n, 1),
            "val": round(agg["val"] / n, 1), "pm": round(agg["plus_minus"] / n, 1),
        },
        "pct": {
            "fg": _pct(fgm, fga), "t2": _pct(agg["t2m"], agg["t2a"]),
            "t3": _pct(agg["t3m"], agg["t3a"]), "tl": _pct(agg["tlm"], agg["tla"]),
            "ts": round(agg["pts"] / ts_den * 100, 1) if ts_den else 0.0,
        },
        "totals": {"pts": agg["pts"], "val": agg["val"], "t3m": agg["t3m"]},
        "last": games[-8:],
        "owner": owner.manager_name if owner else None,
        "owner_member_id": owner.id if owner else None,
        "clause": pick.clause if pick else None,
        "clause_locked": locked, "clause_lock_mins": lock_mins,
        # si se abre la ficha desde una jornada concreta, su partido de ese día
        "game": player_jornada_line(session, league, player_id, jornada) if jornada else None,
    }


def league_players(session: Session, league: FantasyLeague,
                   member) -> list[dict]:
    """Todos los jugadores de la conferencia con su dueño, para el buscador y los
    rankings. Es la foto completa: quién rinde, cuánto vale y de quién es."""
    info = all_priced(session, league)
    now = utcnow()
    dueno: dict[int, tuple] = {}
    for m in _members(session, league.id):
        for p in picks_of(session, m.id):
            locked = bool(p.clause_locked_until and now < p.clause_locked_until)
            dueno[p.player_id] = (m.id, m.manager_name, p.clause, locked)
    en_subasta = listed_player_ids(session, league)
    out = []
    for r in info:
        d = dueno.get(r["player_id"])
        out.append({
            "player_id": r["player_id"], "name": r["name"], "feb_code": r["feb_code"],
            "team": r["team"], "price": r["price"], "fp_avg": r.get("fp_avg", 0),
            "fp_form": r.get("fp_form", 0), "val_avg": r.get("val_avg", 0),
            "pm_avg": r.get("pm_avg", 0), "games": r.get("games", 0),
            "departed": bool(r.get("departed")),
            "owner_member_id": d[0] if d else None,
            "owner": d[1] if d else None,
            "clause": d[2] if d else None,
            "clause_locked": d[3] if d else False,
            "mine": bool(d and member and d[0] == member.id),
            "listed": r["player_id"] in en_subasta,
        })
    out.sort(key=lambda x: -x["fp_avg"])
    return out


def league_clauses(session: Session, league: FantasyLeague,
                   member: Optional[FantasyMember]) -> list[dict]:
    """Todos los jugadores con dueño de la liga y su cláusula, de la más barata a la más
    cara: es el escaparate para ir de clausulazo."""
    info = {r["player_id"]: r for r in all_priced(session, league)}
    now = utcnow()
    members = session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league.id)).all()
    out = []
    for m in members:
        for p in picks_of(session, m.id):
            d = info.get(p.player_id, {})
            locked = bool(p.clause_locked_until and now < p.clause_locked_until)
            out.append({
                "player_id": p.player_id, "name": d.get("name", "?"),
                "feb_code": d.get("feb_code"), "team": d.get("team"),
                "price": d.get("price", p.buy_price),
                "fp_avg": d.get("fp_avg", 0), "fp_form": d.get("fp_form", 0),
                "val_avg": d.get("val_avg", 0), "games": d.get("games", 0),
                "clause": p.clause, "clause_locked": locked,
                "clause_lock_mins": int((p.clause_locked_until - now).total_seconds() // 60) if locked else 0,
                "owner_member_id": m.id, "owner": m.manager_name,
                "mine": bool(member and m.id == member.id),
                "starter": p.starter, "departed": bool(d.get("departed")),
            })
    out.sort(key=lambda r: r["clause"])
    return out


def member_squad(session: Session, league: FantasyLeague, member_id: int) -> list[dict]:
    """Plantilla de cualquier mánager (para ver rivales y sus cláusulas)."""
    m = session.get(FantasyMember, member_id)
    if not m or m.league_id != league.id:
        raise ValueError("Mánager no encontrado")
    prices = price_map(session, league)
    info = {r["player_id"]: r for r in all_priced(session, league)}
    now = utcnow()
    out = []
    for p in picks_of(session, member_id):
        d = info.get(p.player_id, {})
        locked = bool(p.clause_locked_until and now < p.clause_locked_until)
        out.append({
            "player_id": p.player_id, "name": d.get("name", "?"), "feb_code": d.get("feb_code"),
            "team": d.get("team"), "price": prices.get(p.player_id, p.buy_price),
            "val_avg": d.get("val_avg", 0), "fp_avg": d.get("fp_avg", 0), "starter": p.starter,
            "clause": p.clause, "clause_locked": locked,
            "clause_lock_mins": int((p.clause_locked_until - now).total_seconds() // 60) if locked else 0,
        })
    out.sort(key=lambda r: -r["price"])
    return {"manager": m.manager_name, "member_id": m.id, "squad": out,
            "budget": m.budget_remaining, "points": m.total_points}


def put_on_sale(session: Session, league: FantasyLeague, member: FantasyMember,
                player_id: int) -> dict:
    """Pone a un jugador en el escaparate.

    No se vende al momento a propósito: durante tres días la liga manda una oferta al
    día, entre un 5% menos y un 10% más de su valor. Cada una vale solo 24 horas: al
    llegar la siguiente, la anterior se pierde. Así hay que decidir con lo que hay
    encima de la mesa, en vez de esperar a verlas todas y quedarse la mejor.
    """
    sync_market(session, league)
    _require(session, league, "mercado", what="podrás poner en venta")
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    if pick.sale_started_at:
        raise ValueError("Ese jugador ya está en venta")
    pick.sale_started_at = utcnow()
    pick.sale_offers_made = 0
    session.add(pick)
    session.commit()
    sync_offers(session, league)          # la primera oferta entra ya
    pl = session.get(Player, player_id)
    return {"ok": True, "player": _nice(pl.name if pl else None), "days": SALE_DAYS}


def cancel_sale(session: Session, league: FantasyLeague, member: FantasyMember,
                player_id: int) -> dict:
    """Lo retira del escaparate; caducan las ofertas de la liga que siguieran vivas."""
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    pick.sale_started_at = None
    pick.sale_offers_made = 0
    session.add(pick)
    for o in session.exec(select(FantasyOffer).where(
            FantasyOffer.league_id == league.id, FantasyOffer.player_id == player_id,
            FantasyOffer.to_member_id == member.id,
            FantasyOffer.from_member_id == None,            # noqa: E711
            FantasyOffer.status == "pending")).all():
        o.status = "cancelled"
        o.resolved_at = utcnow()
        session.add(o)
    session.commit()
    return {"ok": True}


def sync_offers(session: Session, league: FantasyLeague) -> None:
    """Genera las ofertas de la liga que toquen y caduca las pasadas de plazo.

    Perezoso, como el mercado: se llama en cada consulta y así no hace falta ningún
    proceso en segundo plano.
    """
    ahora = utcnow()
    cambios = False

    for o in session.exec(select(FantasyOffer).where(
            FantasyOffer.league_id == league.id, FantasyOffer.status == "pending")).all():
        if o.expires_at and o.expires_at <= ahora:
            o.status = "expired"
            o.resolved_at = ahora
            session.add(o)
            cambios = True

    precios = price_map(session, league)
    for m in _members(session, league.id):
        for pick in picks_of(session, m.id):
            if not pick.sale_started_at:
                continue
            fin = pick.sale_started_at + timedelta(days=SALE_DAYS)   # fin del escaparate
            if ahora >= fin and pick.sale_offers_made >= SALE_DAYS:
                pick.sale_started_at = None      # se acabó el escaparate
                pick.sale_offers_made = 0
                session.add(pick)
                cambios = True
                continue
            # una oferta por día: la primera al ponerlo en venta, luego a las 24h y 48h
            toca = pick.sale_started_at + timedelta(days=pick.sale_offers_made)
            if pick.sale_offers_made >= SALE_DAYS or ahora < toca:
                continue
            valor = precios.get(pick.player_id, pick.buy_price)
            factor = 1 + random.uniform(SALE_MIN, SALE_MAX)
            importe = max(PRICE_MIN, round(valor * factor, 1))
            # Cada oferta vale SOLO su día: caduca justo cuando entra la siguiente. Si
            # se acumularan las tres no habría decisión que tomar, bastaba con esperar
            # a verlas todas y quedarse la mejor.
            caduca = pick.sale_started_at + timedelta(days=pick.sale_offers_made + 1)
            session.add(FantasyOffer(
                league_id=league.id, player_id=pick.player_id, to_member_id=m.id,
                from_member_id=None, amount=importe, expires_at=caduca))
            pick.sale_offers_made += 1
            session.add(pick)
            pl = session.get(Player, pick.player_id)
            quedan = SALE_DAYS - pick.sale_offers_made
            _notify(session, league, m, "offer",
                    f"Oferta por {_nice(pl.name if pl else None)}",
                    f"Te ofrecen {importe} M€ · solo vale 24 h"
                    + (f", luego llegará otra ({quedan} más)" if quedan else
                       " y es la última"))
            cambios = True
    if cambios:
        session.commit()


def make_offer(session: Session, league: FantasyLeague, member: FantasyMember,
               player_id: int, amount: float) -> dict:
    """Oferta a otro mánager por uno de sus jugadores. Él decide."""
    sync_market(session, league)
    _require(session, league, "mercado", what="podrás hacer ofertas")
    amount = round(float(amount), 1)
    if amount <= 0:
        raise ValueError("La oferta tiene que ser mayor que cero")
    pick = session.exec(select(FantasyPick).join(
        FantasyMember, FantasyMember.id == FantasyPick.member_id).where(
        FantasyMember.league_id == league.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("Ese jugador no lo tiene nadie: sale por el mercado")
    if pick.member_id == member.id:
        raise ValueError("Ese jugador ya es tuyo")
    if len(picks_of(session, member.id)) >= league.squad_size:
        raise ValueError(f"Plantilla llena ({league.squad_size} jugadores)")
    libre = member.budget_remaining - committed_amount(session, member.id)
    if amount > libre + 1e-6:
        raise ValueError(f"Necesitas {amount} M€ libres (tienes {round(libre, 1)})")
    previa = session.exec(select(FantasyOffer).where(
        FantasyOffer.league_id == league.id, FantasyOffer.player_id == player_id,
        FantasyOffer.from_member_id == member.id,
        FantasyOffer.status == "pending")).first()
    if previa:                       # cambiar de idea sí, pero no acumular ofertas
        previa.status = "cancelled"
        previa.resolved_at = utcnow()
        session.add(previa)
    session.add(FantasyOffer(league_id=league.id, player_id=player_id,
                             to_member_id=pick.member_id, from_member_id=member.id,
                             amount=amount, expires_at=utcnow() + timedelta(days=SALE_DAYS)))
    pl = session.get(Player, player_id)
    _notify(session, league, pick.member_id, "offer",
            f"{member.manager_name} quiere a {_nice(pl.name if pl else None)}",
            f"Te ofrece {amount} M€")
    session.commit()
    return {"ok": True, "amount": amount}


def resolve_offer(session: Session, league: FantasyLeague, member: FantasyMember,
                  offer_id: int, accept: bool) -> dict:
    """El dueño acepta o rechaza. Al aceptar se mueve el dinero y el jugador."""
    o = session.get(FantasyOffer, offer_id)
    if not o or o.league_id != league.id:
        raise ValueError("Esa oferta no existe")
    if o.to_member_id != member.id:
        raise ValueError("Esa oferta no es tuya")
    if o.status != "pending":
        raise ValueError("Esa oferta ya no está en pie")
    if not accept:
        o.status = "rejected"
        o.resolved_at = utcnow()
        session.add(o)
        session.commit()
        return {"ok": True, "accepted": False}

    _require(session, league, "mercado", what="podrás cerrar el traspaso")
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == o.player_id)).first()
    if not pick:
        raise ValueError("Ya no tienes a ese jugador")
    pl = session.get(Player, o.player_id)
    nombre = _nice(pl.name if pl else None)
    comprador = session.get(FantasyMember, o.from_member_id) if o.from_member_id else None

    if comprador:      # traspaso entre mánagers
        if len(picks_of(session, comprador.id)) >= league.squad_size:
            raise ValueError(f"{comprador.manager_name} tiene la plantilla llena")
        if o.amount > comprador.budget_remaining + 1e-6:
            raise ValueError(f"{comprador.manager_name} ya no tiene ese dinero")
        comprador.budget_remaining = round(comprador.budget_remaining - o.amount, 1)
        titulares = sum(1 for p in picks_of(session, comprador.id) if p.starter)
        valor = price_map(session, league).get(o.player_id, o.amount)
        session.delete(pick)
        _new_pick(session, league, comprador, o.player_id, o.amount, valor,
                  titulares < league.lineup_size)
        session.add(comprador)
        _log(session, league.id, "signing",
             f"🤝 {comprador.manager_name} ficha a {nombre} de "
             f"{member.manager_name} por {o.amount} M€")
        _notify(session, league, comprador, "signing", f"Has fichado a {nombre}",
                f"{member.manager_name} ha aceptado tus {o.amount} M€")
    else:              # se lo queda la liga
        session.delete(pick)
        _log(session, league.id, "sale",
             f"💸 {member.manager_name} vende a {nombre} por {o.amount} M€")

    member.budget_remaining = round(member.budget_remaining + o.amount, 1)
    session.add(member)
    o.status = "accepted"
    o.resolved_at = utcnow()
    session.add(o)
    for otra in session.exec(select(FantasyOffer).where(
            FantasyOffer.league_id == league.id, FantasyOffer.player_id == o.player_id,
            FantasyOffer.status == "pending")).all():
        otra.status = "cancelled"       # las demás se caen solas
        otra.resolved_at = utcnow()
        session.add(otra)
    session.commit()
    return {"ok": True, "accepted": True, "amount": o.amount,
            "budget_remaining": member.budget_remaining}


def offers_for(session: Session, league: FantasyLeague,
               member: Optional[FantasyMember]) -> dict:
    """Las que te han hecho y las que has hecho tú."""
    if not member:
        return {"received": [], "sent": []}
    sync_offers(session, league)
    info = {r["player_id"]: r for r in all_priced(session, league)}
    nombres = {m.id: m.manager_name for m in _members(session, league.id)}

    def fila(o):
        d = info.get(o.player_id, {})
        return {
            "id": o.id, "player_id": o.player_id, "name": d.get("name", "?"),
            "feb_code": d.get("feb_code"), "team": d.get("team"),
            "price": d.get("price", 0), "fp_avg": d.get("fp_avg", 0),
            "amount": o.amount, "from_member_id": o.from_member_id,
            "from": nombres.get(o.from_member_id) if o.from_member_id else None,
            "to": nombres.get(o.to_member_id),
            "expires_at": o.expires_at.isoformat() + "Z" if o.expires_at else None,
            "created_at": o.created_at.isoformat() + "Z",
        }

    recibidas = session.exec(select(FantasyOffer).where(
        FantasyOffer.league_id == league.id, FantasyOffer.to_member_id == member.id,
        FantasyOffer.status == "pending").order_by(FantasyOffer.id.desc())).all()
    enviadas = session.exec(select(FantasyOffer).where(
        FantasyOffer.league_id == league.id, FantasyOffer.from_member_id == member.id,
        FantasyOffer.status == "pending").order_by(FantasyOffer.id.desc())).all()
    return {"received": [fila(o) for o in recibidas], "sent": [fila(o) for o in enviadas]}


def _ya_jugo(session: Session, player_id: int, jornada: int, era_titular: bool) -> str:
    p = session.get(Player, player_id)
    quien = _nice(p.name) if p else "Ese jugador"
    return (f"{quien} ya ha jugado la jornada {jornada}: "
            + ("no puedes sacarlo del quinteto" if era_titular else "ya no puedes alinearlo")
            + ". Para la jornada siguiente lo tienes libre.")


def set_lineup(session: Session, league: FantasyLeague, member: FantasyMember,
               starter_ids: list[int]) -> dict:
    sync_market(session, league)
    # El quinteto se puede tocar hasta que salte el partido de cada uno: es lo último que
    # se cierra, y se cierra jugador a jugador.
    state = _require(session, league, "mercado", "alineacion",
                     what="podrás cambiar el quinteto")
    if len(starter_ids) > league.lineup_size:
        raise ValueError(f"Solo puedes alinear {league.lineup_size} titulares")
    picks = picks_of(session, member.id)
    if not set(starter_ids).issubset({p.player_id for p in picks}):
        raise ValueError("Algún titular no está en tu plantilla")
    # Los que ya han jugado esta jornada se quedan como estaban: ni se meten ni se sacan.
    # Sin esto, el sábado se podría alinear al que hizo 30 puntos el viernes.
    j = state["jornada"]
    sellados = sellados_de(session, league, member.id, j)
    for pid, era in sellados.items():
        if (pid in starter_ids) != era:
            raise ValueError(_ya_jugo(session, pid, j, era))
    # Y los que NO están sellados pero su partido ya ha saltado: son fichajes posteriores
    # a su propio partido. Se pueden tener, pero no alinear en esta jornada.
    nuevos = [pid for pid in starter_ids if pid not in sellados]
    if nuevos:
        jugando = equipos_en_juego(session, league, j)
        if jugando:
            for pid, tid in _equipo_de(session, set(nuevos)).items():
                if tid in jugando:
                    raise ValueError(_ya_jugo(session, pid, j, False))
    for p in picks:
        p.starter = p.player_id in starter_ids
        session.add(p)
    session.commit()
    return {"ok": True, "starters": starter_ids}


# ============================ jornada / clasificación ============================
def pending_matches(session: Session, league: FantasyLeague, jornada: int,
                    solo: Optional[set] = None) -> list[str]:
    """Partidos de esa jornada que aún no se han jugado (aplazados o por disputar).

    Mientras quede alguno no se puede puntuar: los jugadores de esos equipos sumarían cero
    y quien los tuviera alineados se comería un cero que no le corresponde.
    """
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    faltan = []
    for m in session.exec(q).all():
        if solo is not None and m.id not in solo:
            continue
        if m.home_score is None or m.away_score is None:
            local = session.get(Team, m.home_team_id) if m.home_team_id else None
            visit = session.get(Team, m.away_team_id) if m.away_team_id else None
            faltan.append(f"{local.name if local else '?'} - {visit.name if visit else '?'}")
    return faltan


def sin_acta(session: Session, league: FantasyLeague, jornada: int,
             solo: Optional[set] = None) -> list[str]:
    """Partidos ya jugados de esa jornada cuyo BOXSCORE todavía no ha llegado.

    La FEB publica el marcador en el calendario y el acta por otro lado, y a veces tarda
    (o falla). Mientras no esté, sus jugadores no tienen líneas y sumarían cero: es el
    mismo cero injusto que el de un aplazado, solo que más difícil de ver porque el
    partido figura como jugado. Así que la jornada se queda provisional también por esto y
    se recalcula cuando entre el acta.

    Las incomparecencias (`details_unavailable`) no cuentan: hay marcador de oficio pero
    LiveStats no va a servir acta nunca, así que esperar a ella sería esperar para siempre.
    """
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    jugados = [m for m in session.exec(q).all()
               if (solo is None or m.id in solo)
               and m.home_score is not None and m.away_score is not None
               and not m.details_unavailable]
    if not jugados:
        return []
    con_acta = set(session.exec(select(PlayerMatchStat.match_id).where(
        PlayerMatchStat.match_id.in_([m.id for m in jugados]))).all())
    faltan = []
    for m in jugados:
        if m.id not in con_acta:
            local = session.get(Team, m.home_team_id) if m.home_team_id else None
            visit = session.get(Team, m.away_team_id) if m.away_team_id else None
            faltan.append(f"{local.name if local else '?'} - {visit.name if visit else '?'}")
    return faltan


def jornada_empezada(session: Session, league: FantasyLeague, jornada: int) -> bool:
    """¿Hay ya algún resultado de esa jornada? Entonces ha empezado, mande lo que mande
    el calendario. Es la red de seguridad contra las horas mal publicadas."""
    q = select(Match.id).where(Match.competition == league.competition,
                               Match.season == league.season,
                               Match.jornada_num == jornada,
                               Match.home_score != None,  # noqa: E711
                               Match.away_score != None)  # noqa: E711
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    return session.exec(q.limit(1)).first() is not None


def _equipos_pendientes(session: Session, league: FantasyLeague, jornada: int) -> set[int]:
    """Equipos cuyo partido de esa jornada aún no cuenta: sin jugarse o sin acta."""
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    ms = session.exec(q).all()
    jugados = [m for m in ms if m.home_score is not None and m.away_score is not None
               and not m.details_unavailable]
    con_acta = set(session.exec(select(PlayerMatchStat.match_id).where(
        PlayerMatchStat.match_id.in_([m.id for m in jugados]))).all()) if jugados else set()
    out: set[int] = set()
    for m in ms:
        sin_jugar = m.home_score is None or m.away_score is None
        sin_datos = (not sin_jugar and not m.details_unavailable and m.id not in con_acta)
        if sin_jugar or sin_datos:
            out.update(x for x in (m.home_team_id, m.away_team_id) if x)
    return out


def sim_pendientes(session: Session, league: FantasyLeague, jornada: int) -> list[str]:
    """Los que en simulación todavía no se han disputado, con nombres, para poder decir
    exactamente qué falta antes de cerrar la jornada."""
    jugados = sim_jugados(session, league, jornada)
    if jugados is None:
        return []
    ids = [m for m in sim_partidos(session, league, jornada) if m not in jugados]
    faltan = []
    for mid in ids:
        m = session.get(Match, mid)
        if not m:
            continue
        local = session.get(Team, m.home_team_id) if m.home_team_id else None
        visit = session.get(Team, m.away_team_id) if m.away_team_id else None
        faltan.append(f"{local.name if local else '?'} - {visit.name if visit else '?'}")
    return faltan


def resting_teams(session: Session, league: FantasyLeague, jornada: int) -> set[int]:
    """Equipos de la conferencia que NO juegan esa jornada.

    Con un número impar de equipos (el grupo E-B de 3ª FEB tiene 13) cada jornada
    descansa uno. Sus jugadores suman cero, igual que si no hubieran jugado, pero no es
    lo mismo y confunde muchísimo: parece que la app se ha comido un partido. Así que se
    marca aparte y se dice "descansa", que es lo que pasa de verdad.
    """
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    tq = select(Team).where(Team.competition == league.competition,
                            Team.season == league.season)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
        tq = tq.where(Team.grupo == league.grupo)
    juegan: set[int] = set()
    for m in session.exec(q).all():
        juegan.update(x for x in (m.home_team_id, m.away_team_id) if x)
    return {t.id for t in session.exec(tq).all() if t.id not in juegan}


def jornada_matches(session: Session, league: FantasyLeague, jornada: int) -> list[dict]:
    """Los partidos de una jornada con su estado, para que se VEA por qué sigue abierta.

    La FEB no dice si un partido se ha movido, así que se deduce comparando con el día
    principal de la jornada (el que juega la mayoría): dos días o más antes es un
    adelanto, dos o más después un aplazamiento.
    """
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    ms = session.exec(q).all()
    principal = dia_principal([m.match_date for m in ms])
    now = utcnow()
    fin_partido = timedelta(hours=MATCH_LEN_H)
    # En simulación la base ya tiene TODOS los resultados, así que sin este filtro la
    # jornada se destriparía entera nada más empezar: el marcador de un partido que aún no
    # se ha "jugado" no se manda, y el partido figura como pendiente.
    disputados = sim_jugados(session, league, jornada)
    out = []
    for m in ms:
        local = session.get(Team, m.home_team_id) if m.home_team_id else None
        visit = session.get(Team, m.away_team_id) if m.away_team_id else None
        jugado = m.home_score is not None and m.away_score is not None
        if disputados is not None and m.id not in disputados:
            jugado = False
        if jugado:
            estado = "jugado"
        elif m.start_at and m.start_at <= now < m.start_at + fin_partido:
            estado = "en_juego"
        elif m.start_at and now >= m.start_at + fin_partido:
            estado = "sin_resultado"   # pasó la hora y la FEB aún no ha publicado nada
        else:
            estado = "pendiente"
        movido = None
        if principal and not jugado:
            # Aplazado es tanto el que ya tiene fecha nueva y posterior como el que sigue
            # sin jugarse dos días después del fin de semana de la jornada: cuando la FEB
            # mueve un partido a veces tarda en publicar el nuevo día, y hasta entonces
            # aparecía como un partido suelto sin explicación.
            if es_aplazado(m.match_date, principal) or (now.date() - principal).days >= 2:
                movido = "aplazado"
            elif m.match_date and (m.match_date - principal).days <= -2:
                movido = "adelantado"
        out.append({
            "match_id": m.id, "jornada": jornada,
            "home": local.name if local else "?", "away": visit.name if visit else "?",
            "home_id": m.home_team_id, "away_id": m.away_team_id,
            "home_score": m.home_score if jugado else None,
            "away_score": m.away_score if jugado else None,
            "date": m.match_date.isoformat() if m.match_date else None,
            "start_at": m.start_at.isoformat() + "Z" if m.start_at else None,
            "status": estado, "moved": movido,
        })
    out.sort(key=lambda r: (r["date"] or "9999-12-31", r["start_at"] or "9999"))
    return out


def next_match_for_team(session: Session, league: FantasyLeague,
                        team_id: Optional[int], jornada: Optional[int] = None) -> Optional[dict]:
    """El siguiente partido de un equipo PARA ESTA LIGA: contra quién, cuándo y dónde.

    La referencia es la jornada que le toca a la liga, no el calendario real: jugando una
    temporada ya disputada (modo repetición) todos los partidos tienen resultado, y
    filtrar por "sin resultado" no devolvía nada. El marcador no se manda nunca: sería
    destripar la jornada que está por jugarse.
    """
    if not team_id:
        return None
    j = jornada if jornada is not None else league_state(session, league)["jornada"]
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num != None,  # noqa: E711
                            Match.jornada_num >= j,
                            ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)))
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    cand = sorted(session.exec(q).all(), key=lambda m: (m.jornada_num,
                                                        m.match_date or date.max,
                                                        m.start_at or datetime.max))
    if not cand:
        return None
    m = cand[0]
    en_casa = m.home_team_id == team_id
    # si su siguiente partido es de una jornada posterior, esta la descansa
    descansa = m.jornada_num != j
    rival = session.get(Team, m.away_team_id if en_casa else m.home_team_id)
    return {
        "jornada": m.jornada_num, "home": en_casa, "rests_now": descansa,
        "rival": rival.name if rival else "?",
        "rival_id": rival.id if rival else None,
        "date": m.match_date.isoformat() if m.match_date else None,
        "start_at": m.start_at.isoformat() + "Z" if m.start_at else None,
    }


def _after_jornada(session: Session, league: FantasyLeague) -> None:
    """Reprograma el calendario al puntuar una jornada: siguiente día de partido y
    reapertura del mercado (con una tanda nueva, la de la semana que empieza)."""
    now = utcnow()
    # Puntuar con el mercado abierto (el botón del admin) dejaría una tanda huérfana, sin
    # hora de cierre y por tanto imposible de resolver: se resuelve aquí y se abre otra.
    if league.market_open:
        _resolve_round(session, league)
    league.market_closes_at = None
    if league.current_jornada >= league.max_jornada:
        league.kickoff_at = None
        league.market_opens_at = None
        return
    # Se cuenta desde el salto anterior para no perder el día/hora de la liga aunque la
    # jornada se puntúe tarde; si aun así se ha quedado atrás, se salta a la siguiente semana.
    nxt = _weekly_slot(league.kickoff_at or now, league.play_weekday, league.play_hour)
    while nxt <= now + timedelta(hours=league.market_close_before_h):
        nxt = _weekly_slot(nxt, league.play_weekday, league.play_hour)
    league.kickoff_at = nxt
    # En cuanto la jornada queda puntuada se reabre el mercado: la semana empieza aquí.
    league.market_opens_at = now


def _inicio_de(league: FantasyLeague, m: Match) -> Optional[datetime]:
    """Cuándo saltó (o salta) un partido. El DÍA manda sobre la hora: con un adelanto que
    la FEB publica tarde, la hora se queda en la vieja y diría que aún no se ha jugado."""
    if m.start_at and m.match_date and m.match_date < m.start_at.date():
        return _at(m.match_date, league.play_hour)
    if m.start_at:
        return m.start_at
    return _at(m.match_date, league.play_hour) if m.match_date else None


def equipos_en_juego(session: Session, league: FantasyLeague,
                     jornada: int) -> dict[int, datetime]:
    """Equipos cuyo partido de la jornada YA ha saltado -> cuándo saltó.

    Sus jugadores dejan de poder moverse del quinteto: lo que hicieron ya está hecho.
    """
    q = select(Match).where(Match.competition == league.competition,
                            Match.season == league.season,
                            Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    now = utcnow()
    # En simulación el reloj no dice nada (la temporada está jugada entera): quien manda
    # es el paso del simulador.
    disputados = sim_jugados(session, league, jornada) if league.sim_mode else None
    out: dict[int, datetime] = {}
    for m in session.exec(q).all():
        if disputados is not None:
            if m.id not in disputados:
                continue
            for tid in (m.home_team_id, m.away_team_id):
                if tid:
                    out[tid] = now
            continue
        inicio = _inicio_de(league, m)
        jugado = m.home_score is not None and m.away_score is not None
        if not (jugado or (inicio and now >= inicio)):
            continue
        for tid in (m.home_team_id, m.away_team_id):
            if tid:
                out[tid] = inicio or now
    return out


def _equipo_de(session: Session, player_ids: set[int]) -> dict[int, int]:
    """player_id -> team_id, por su partido más reciente. Solo para los que se piden."""
    if not player_ids:
        return {}
    q = (select(PlayerMatchStat.player_id, PlayerMatchStat.team_id, Match.jornada_num)
         .join(Match, Match.id == PlayerMatchStat.match_id)
         .where(PlayerMatchStat.player_id.in_(list(player_ids))))
    ultimo: dict[int, int] = {}
    out: dict[int, int] = {}
    for pid, tid, j in session.exec(q):
        if j is not None and j >= ultimo.get(pid, -1):
            ultimo[pid], out[pid] = j, tid
    return out


def sellar_quinteto(session: Session, league: FantasyLeague, jornada: int,
                    final: bool = False) -> int:
    """Cierra el quinteto de una jornada POR PARTIDOS, no de golpe. Idempotente.

    Un jugador queda sellado en cuanto salta SU partido: a partir de ahí ni entra ni sale
    del quinteto de esa jornada, porque lo que hizo ya está hecho y dejarlo abierto sería
    poder comprar puntos ya conocidos. Los demás se siguen tocando con normalidad, que es
    lo que permite que un partido adelantado no le cierre la semana a toda la liga.

    Con `final=True` (al puntuar la jornada) se sella todo lo que quede: a partir de ese
    momento la foto ya no cambia, aunque falte un aplazado por disputarse.
    """
    filas = {r.member_id: r for r in session.exec(select(FantasyLineup).where(
        FantasyLineup.league_id == league.id, FantasyLineup.jornada == jornada)).all()}
    miembros = session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league.id)).all()
    if not miembros:
        return 0

    equipos = {} if final else equipos_en_juego(session, league, jornada)
    if not final and not equipos:
        return 0

    picks = {m.id: picks_of(session, m.id) for m in miembros}
    de_quien = {}
    if not final:
        todos = {p.player_id for ps in picks.values() for p in ps}
        de_quien = _equipo_de(session, todos)

    tocados = 0
    for m in miembros:
        row = filas.get(m.id)
        if row is None:
            row = FantasyLineup(league_id=league.id, member_id=m.id, jornada=jornada,
                                player_ids="[]", sealed="{}")
            session.add(row)
            filas[m.id] = row
        try:
            sellados = json.loads(row.sealed) if row.sealed else {}
        except (TypeError, ValueError):
            sellados = {}
        cambio = False
        for p in picks[m.id]:
            if str(p.player_id) in sellados:
                continue
            inicio = None if final else equipos.get(de_quien.get(p.player_id))
            if not final and inicio is None:
                continue
            # Quien llega a la plantilla DESPUÉS de su propio partido no puntúa esa
            # jornada, aunque entre de titular: un clausulazo coloca al fichado en el
            # quinteto si hay hueco, y eso sería comprar puntos ya conocidos.
            titular = bool(p.starter) and (final or p.created_at <= inicio)
            sellados[str(p.player_id)] = titular
            cambio = True
        if cambio or row.player_ids in (None, "", "[]"):
            row.sealed = json.dumps(sellados)
            row.player_ids = json.dumps([int(pid) for pid, tit in sellados.items() if tit])
            session.add(row)
            tocados += 1 if cambio else 0
    session.commit()
    return tocados


def sellados_de(session: Session, league: FantasyLeague, member_id: int,
                jornada: int) -> dict[int, bool]:
    """player_id -> si estaba de titular, para los jugadores ya cerrados de esa jornada."""
    row = session.exec(select(FantasyLineup).where(
        FantasyLineup.league_id == league.id, FantasyLineup.member_id == member_id,
        FantasyLineup.jornada == jornada)).first()
    if not row or not row.sealed:
        return {}
    try:
        return {int(k): bool(v) for k, v in json.loads(row.sealed).items()}
    except (TypeError, ValueError):
        return {}


def freeze_lineups(session: Session, league: FantasyLeague, jornada: int) -> int:
    """Cierra la jornada entera de golpe. Es el sellado final, ya sin partidos por saltar."""
    return sellar_quinteto(session, league, jornada, final=True)


def frozen_lineup(session: Session, league: FantasyLeague, member_id: int,
                  jornada: int) -> Optional[list[int]]:
    """El quinteto congelado de esa jornada, o None si no llegó a guardarse."""
    row = session.exec(select(FantasyLineup).where(
        FantasyLineup.league_id == league.id, FantasyLineup.member_id == member_id,
        FantasyLineup.jornada == jornada)).first()
    if not row:
        return None
    try:
        return json.loads(row.player_ids)
    except (TypeError, ValueError):
        return None


def sim_cerrar_mercado(session: Session, league: FantasyLeague) -> dict:
    """Paso 1 · viernes noche: se cierra el mercado y se congelan los quintetos."""
    if not league.sim_mode:
        return {"ok": False, "message": "Esta liga va con el calendario real de la FEB"}
    if sim_step_de(session, league) != 0:
        return {"ok": False, "message": "La jornada ya está en juego"}
    nxt = league.current_jornada + 1
    ade, _ = sim_reparto(session, league, nxt)
    league.sim_step = 1
    # El adelantado va el primero de la lista y se jugó antes de cerrar el mercado.
    league.sim_played = 1 if ade else 0
    # Los aplazados de hace dos jornadas se recuperan ahora: es cuando la FEB los suele
    # meter entre semana. `completar()` sube los puntos en el siguiente `sync_market`.
    pend = _aplazados_sim(league)
    recuperados = [j for j in pend if j <= nxt - 2]
    for j in recuperados:
        mid = pend.pop(j)
        m = session.get(Match, mid)
        nombre = _nombre_partido(session, m) if m else "un partido"
        _log(session, league.id, "jornada",
             f"🏀 Se recupera el aplazado de la jornada {j}: {nombre}")
    if recuperados:
        _guardar_aplazados(league, pend)
    session.add(league)
    _log(session, league.id, "jornada",
         f"🔒 Jornada {nxt}: mercado cerrado y quintetos bloqueados")
    session.commit()
    if recuperados:
        completar(session, league)
    return {"ok": True, "step": 1, "jornada": nxt,
            "total": len(sim_partidos(session, league, nxt)),
            "played": league.sim_played, "recuperados": recuperados}


def sim_jugar(session: Session, league: FantasyLeague, cuantos: int = 0) -> dict:
    """Paso 2 · se disputan algunos partidos y ya se puede ir mirando cómo va.

    Por defecto, la mitad de lo que quede (mínimo uno): así el segundo clic deja jornada
    a medias de verdad, que es la gracia de poder asomarse antes del final.
    """
    if not league.sim_mode:
        return {"ok": False, "message": "Esta liga va con el calendario real de la FEB"}
    if sim_step_de(session, league) != 1:
        return {"ok": False, "message": "Primero cierra el mercado"}
    nxt = league.current_jornada + 1
    total = len(sim_partidos(session, league, nxt))
    quedan = total - league.sim_played
    if quedan <= 0:
        return {"ok": False, "message": "Ya se han jugado todos los partidos de la jornada"}
    n = cuantos if cuantos > 0 else max(1, quedan // 2)
    league.sim_played = min(total, league.sim_played + n)
    session.add(league)
    jugados = league.sim_played
    _log(session, league.id, "jornada",
         f"🏀 Jornada {nxt}: se han jugado {jugados} de {total} partidos")
    session.commit()
    return {"ok": True, "step": 1, "jornada": nxt, "total": total, "played": jugados,
            "remaining": total - jugados}


def sim_finalizar(session: Session, league: FantasyLeague) -> dict:
    """Paso 3 · domingo noche: se cierra la jornada y se puntúa.

    Si a la base le faltara el resultado de algún partido, la jornada se cierra igual y
    queda marcada como incompleta: sus puntos son provisionales y suben solos en cuanto
    aparezca el resultado. Nadie se come un cero definitivo que no le toca.
    """
    if not league.sim_mode:
        return advance(session, league)
    if sim_step_de(session, league) != 1:
        return {"ok": False, "message": "La jornada todavía no ha empezado"}
    nxt = league.current_jornada + 1
    # Domingo noche: se disputa lo que quedara y se cierra.
    total = len(sim_partidos(session, league, nxt))
    _, apl = sim_reparto(session, league, nxt)
    # El aplazado va el último de la lista y NO se juega: la jornada se cierra sin él y
    # queda en provisional, que es de lo que va todo esto.
    quedaban = total - (1 if apl else 0) - league.sim_played   # los que faltaban por jugar
    league.sim_played = total - (1 if apl else 0)
    if apl:
        pend = _aplazados_sim(league)
        pend[nxt] = apl
        _guardar_aplazados(league, pend)
        m = session.get(Match, apl)
        _log(session, league.id, "jornada",
             f"📆 Jornada {nxt}: se aplaza {_nombre_partido(session, m) if m else 'un partido'}")
    session.add(league)
    session.commit()

    res = advance(session, league)
    if not res.get("ok"):
        return res          # a la base le falta algún resultado: se deja la jornada abierta

    league.sim_step = 0
    league.sim_played = 0
    session.add(league)
    session.commit()
    res["jugados_al_cerrar"] = quedaban
    return res


def jornada_falta(session: Session, league: FantasyLeague, jornada: int) -> dict:
    """Lo que impide dar una jornada por definitiva, con los dos motivos separados.

    `faltan` son partidos por disputarse (un aplazado) y `sin_acta` partidos ya jugados
    cuyo boxscore no ha llegado. Los dos dejan a alguien con un cero que no le toca, así
    que los dos mantienen la jornada en provisional; pero se cuentan aparte porque al
    usuario hay que decírselo con palabras distintas.
    """
    if league.sim_mode:
        # La base tiene todos los resultados desde el principio, así que preguntarle a
        # ella no sirve para saber qué se ha jugado: eso lo dice el simulador. Pero de los
        # que SÍ ha disputado hay que mirarla igual, por si a alguno le falta el resultado
        # o el acta: ese cero también es injusto, y en simulación pasaría desapercibido.
        faltan = sim_pendientes(session, league, jornada)
        disputados = sim_jugados(session, league, jornada)
        actas = sin_acta(session, league, jornada, solo=disputados)
        faltan = faltan + pending_matches(session, league, jornada, solo=disputados)
        return {"faltan": faltan, "sin_acta": actas, "completa": not faltan and not actas}
    faltan = pending_matches(session, league, jornada)
    actas = sin_acta(session, league, jornada)
    return {"faltan": faltan, "sin_acta": actas, "completa": not faltan and not actas}


def _falta_texto(faltan: list[str], sin_acta_: list[str] = ()) -> str:
    """"falta X" / "faltan N partidos", que es como se dice en toda la app."""
    if faltan:
        return (f"falta por jugarse {faltan[0]}" if len(faltan) == 1
                else f"faltan {len(faltan)} partidos por jugarse")
    if sin_acta_:
        return (f"falta el acta de {sin_acta_[0]}" if len(sin_acta_) == 1
                else f"faltan las actas de {len(sin_acta_)} partidos")
    return ""


def advance(session: Session, league: FantasyLeague) -> dict:
    """Puntúa la jornada y pasa a la siguiente.

    Se puntúa con lo que se haya jugado. Si queda algún partido (un aplazado), la jornada
    se cierra igual y queda marcada como incompleta: sus puntos son provisionales y
    `completar()` los sube cuando la FEB publique el resultado. Antes se plantaba aquí y
    la liga no se movía, lo que en la práctica costaba una semana de mercado a todos por
    un partido que a lo mejor no le tocaba a nadie.
    """
    if league.current_jornada >= league.max_jornada:
        return {"ok": False, "done": True, "message": "La temporada ya está completa"}
    nxt = league.current_jornada + 1
    falta = jornada_falta(session, league, nxt)
    faltan, actas, completa = falta["faltan"], falta["sin_acta"], falta["completa"]
    pts = jornada_points(session, league, nxt)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    breakdown = []
    for m in members:
        # el de aquel día, no el de ahora: entre medias puede haber pasado un mercado
        # entero si la jornada se quedó esperando a un aplazado
        starters = frozen_lineup(session, league, m.id, nxt)
        if starters is None:
            starters = [p.player_id for p in picks_of(session, m.id) if p.starter]
        gained = round(sum(pts.get(pid, 0.0) for pid in starters), 1)
        m.total_points = round(m.total_points + gained, 1)
        session.add(m)
        # se guarda el desglose (con el quinteto de ESE momento): en el miembro solo queda
        # el acumulado, y la plantilla cambiará antes de que nadie mire atrás
        session.add(FantasyJornadaScore(league_id=league.id, member_id=m.id, jornada=nxt,
                                        points=gained, starters=json.dumps(starters),
                                        complete=completa))
        breakdown.append({"member_id": m.id, "manager": m.manager_name, "gained": gained})
    league.current_jornada = nxt
    # Las apuestas se liquidan con los mismos resultados que acaban de puntuar. Si falta
    # algún partido se esperan: una pata sobre el aplazado se daría por anulada (dinero
    # devuelto) cuando en realidad todavía se va a jugar. Las resuelve `completar()`.
    if completa:
        _resolver_apuestas(session, league, nxt)
    _after_jornada(session, league)
    session.add(league)
    best = max(breakdown, key=lambda b: b["gained"], default=None)
    coletilla = "" if completa else f" · provisional, {_falta_texto(faltan, actas)}"
    _log(session, league.id, "jornada",
         f"📅 Jornada {nxt} puntuada"
         + (f" · mejor: {best['manager']} ({best['gained']} pts)" if best else "") + coletilla)
    # a cada uno, lo suyo: sus puntos y en qué puesto ha quedado esa jornada
    orden = sorted(breakdown, key=lambda b: -b["gained"])
    for i, row in enumerate(orden):
        pos = orden[i - 1]["pos"] if i and row["gained"] == orden[i - 1]["gained"] else i + 1
        row["pos"] = pos
        cuerpo = (f"{pos}º de {len(orden)}" if len(orden) > 1 else "")
        if best and row["member_id"] == best["member_id"] and len(orden) > 1:
            cuerpo = f"¡Has ganado la jornada! {pos}º de {len(orden)}"
        if not completa:
            # nadie ha ganado nada todavía: lo que toca decir es que esto puede cambiar
            cuerpo = (f"Provisional: {_falta_texto(faltan, actas)}"
                      + (f" · {pos}º de {len(orden)}" if len(orden) > 1 else ""))
        _notify(session, league, row["member_id"], "jornada",
                f"Jornada {nxt} · has hecho {row['gained']} puntos", cuerpo)
    session.commit()
    return {"ok": True, "jornada": nxt, "breakdown": breakdown, "pending": faltan,
            "sin_acta": actas, "complete": completa,
            "done": league.current_jornada >= league.max_jornada}


def _resolver_apuestas(session: Session, league: FantasyLeague, jornada: int) -> None:
    try:
        from . import bets as bets_mod
        bets_mod.resolver(session, league, jornada)
        bets_mod.quiniela_resolver(session, league, jornada)
    except Exception as e:  # noqa: BLE001 - una apuesta rota no puede bloquear la jornada
        print(f"[apuestas] no se pudieron resolver las de la jornada {jornada}: {e}", flush=True)


def jornadas_incompletas(session: Session, league: FantasyLeague) -> list[dict]:
    """Jornadas ya puntuadas a las que todavía les falta algún partido por disputarse.

    Es lo que la app enseña para que se entienda por qué unos puntos pueden subir solos.
    """
    js = sorted({sc.jornada for sc in session.exec(select(FantasyJornadaScore).where(
        FantasyJornadaScore.league_id == league.id,
        FantasyJornadaScore.complete == False)).all()})  # noqa: E712
    out = []
    for j in js:
        falta = jornada_falta(session, league, j)
        if not falta["completa"]:
            out.append({"jornada": j, "faltan": falta["faltan"],
                        "sin_acta": falta["sin_acta"]})
    return out


def completar(session: Session, league: FantasyLeague) -> list[dict]:
    """Rehace las jornadas que se puntuaron a medias, ahora que hay más resultados.

    Se recalcula sobre la MISMA foto del quinteto (`starters` de aquel día), así que da
    igual lo que haya pasado con la plantilla entre medias: el que estaba alineado cuando
    saltó la jornada es el que suma. Solo se mueve la diferencia, de modo que pasar dos
    veces por aquí no regala puntos. Idempotente: es lo que permite llamarla en cada
    `sync_market`.
    """
    filas = session.exec(select(FantasyJornadaScore).where(
        FantasyJornadaScore.league_id == league.id,
        FantasyJornadaScore.complete == False)).all()  # noqa: E712
    if not filas:
        return []
    porjornada: dict[int, list] = {}
    for sc in filas:
        porjornada.setdefault(sc.jornada, []).append(sc)

    cambios = []
    for j, scores in sorted(porjornada.items()):
        falta = jornada_falta(session, league, j)
        completa = falta["completa"]
        pts = jornada_points(session, league, j)
        subidas = []
        for sc in scores:
            if not sc.starters:
                # Sin foto no hay nada que recalcular: recalcular con la plantilla de hoy
                # sería repartir los puntos de aquel día entre quien tenga al jugador
                # ahora, y con `starters` vacío directamente los borraría. Se deja como
                # está (no debería pasar: `advance` siempre guarda la foto).
                sc.complete = True
                session.add(sc)
                continue
            starters = json.loads(sc.starters)
            nuevo = round(sum(pts.get(pid, 0.0) for pid in starters), 1)
            delta = round(nuevo - sc.points, 1)
            if delta:
                m = session.get(FantasyMember, sc.member_id)
                if m:
                    m.total_points = round(m.total_points + delta, 1)
                    session.add(m)
                    subidas.append((m, delta, nuevo))
                sc.points = nuevo
            sc.complete = completa
            session.add(sc)
        if completa:
            # ya está entera: se liquidan las apuestas que se habían quedado esperando
            _resolver_apuestas(session, league, j)
            _log(session, league.id, "jornada",
                 f"✅ Jornada {j} completa: ya se ha jugado todo lo que faltaba")
        for m, delta, nuevo in subidas:
            señal = "+" if delta > 0 else ""
            _notify(session, league, m.id, "jornada",
                    f"Jornada {j} · {señal}{delta} puntos al jugarse lo que faltaba",
                    f"Se te quedan en {nuevo}")
        cambios.append({"jornada": j, "completa": completa, "faltan": falta["faltan"],
                        "sin_acta": falta["sin_acta"], "movidos": len(subidas)})
    session.commit()
    return cambios


def _recover_starters(league: FantasyLeague, picks: list, pts: dict, target: float,
                      jornada: int) -> Optional[list[int]]:
    """Deduce el quinteto de una jornada que se puntuó antes de guardarlo.

    Lo que sí quedó escrito es el TOTAL de esa jornada, y eso basta casi siempre: se buscan
    los jugadores que tenía entonces (los fichados después quedan descartados) cuya suma da
    exactamente ese total. Se recorren en un orden fijo —primero los que jugaron y más
    puntuaron— para que la respuesta no dependa de nada que pueda cambiar, y el resultado se
    guarda: se deduce una vez y ya no se vuelve a mover.
    """
    import itertools
    cands = [p.player_id for p in picks if p.buy_jornada <= jornada]
    # Solo vale un quinteto COMPLETO, y hace falta que sigan estando todos los candidatos:
    # con menos, cualquier par que sumara el total pasaba por quinteto de la jornada. Si el
    # mánager ya ha vendido a medio equipo, esa jornada no se puede reconstruir y punto.
    if len(cands) < league.lineup_size:
        return None
    cands.sort(key=lambda pid: (pid not in pts, -pts.get(pid, 0.0), pid))
    for combo in itertools.combinations(cands, league.lineup_size):
        if abs(sum(pts.get(pid, 0.0) for pid in combo) - target) < 0.05:
            return list(combo)
    return None


# Las categorías del resumen. El orden es el del titular: la valoración manda porque es la
# medida que la FEB usa para el MVP, y el resto cuenta la jornada desde otro ángulo.
RESUMEN_CATEGORIAS = [
    ("val", "Más valorado", "de valoración"),
    ("pts", "Máximo anotador", "puntos"),
    ("treb", "Más rebotes", "rebotes"),
    ("ast", "Más asistencias", "asistencias"),
    ("t3m", "Más triples", "triples"),
    ("plus_minus", "Mejor +/-", "de diferencial"),
]


def jornada_resumen(session: Session, league: FantasyLeague,
                    jornada: Optional[int] = None) -> dict:
    """Los mejores de una jornada en la conferencia de la liga.

    Sale al entrar cuando la jornada ya está puntuada: es el momento en el que apetece
    saber quién la rompió, y hasta ahora había que ir jugador a jugador para enterarse.
    Mira la conferencia entera, no solo los fichados: parte de la gracia es ver al que se
    salió estando libre en el mercado.
    """
    j = jornada if jornada is not None else league.current_jornada
    if j <= 0:
        return {"jornada": 0, "lideres": [], "partidos": 0, "completa": True, "faltan": []}
    # Lo primero que hay que decir de un resumen es si está entero: con un aplazado por
    # medio, el palmarés que se canta aquí todavía puede cambiar.
    falta = jornada_falta(session, league, j)
    faltan, completa = falta["faltan"], falta["completa"]

    q = (
        select(Player.id, Player.name, Player.feb_code, Team.name,
               PlayerMatchStat.val, PlayerMatchStat.pts, PlayerMatchStat.treb,
               PlayerMatchStat.ast, PlayerMatchStat.t3m, PlayerMatchStat.plus_minus,
               PlayerMatchStat.match_id)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(Team.competition == league.competition, Team.season == league.season,
               Match.jornada_num == j)
    )
    if league.grupo:
        q = q.where(Team.grupo == league.grupo)

    filas, partidos = [], set()
    for (pid, nombre, feb, equipo, val, pts, treb, ast, t3m, pm, mid) in session.exec(q):
        partidos.add(mid)
        filas.append({"player_id": pid, "name": nombre, "feb_code": feb, "team": equipo,
                      "val": val or 0, "pts": pts or 0, "treb": treb or 0,
                      "ast": ast or 0, "t3m": t3m or 0, "plus_minus": pm or 0})
    if not filas:
        return {"jornada": j, "lideres": [], "partidos": 0,
                "completa": completa, "faltan": faltan,
                "sin_acta": falta["sin_acta"]}

    # De quién es cada uno en ESTA liga, para poder decir "y lo tiene Marta".
    duenos = {
        pick.player_id: m.manager_name
        for pick, m in session.exec(
            select(FantasyPick, FantasyMember)
            .join(FantasyMember, FantasyMember.id == FantasyPick.member_id)
            .where(FantasyMember.league_id == league.id)).all()
    }

    lideres = []
    for clave, titulo, unidad in RESUMEN_CATEGORIAS:
        mejor = max(filas, key=lambda f: f[clave])
        if mejor[clave] <= 0:
            continue     # nadie rebotó ni asistió: mejor callar que enseñar un cero
        lideres.append({
            "clave": clave, "titulo": titulo, "unidad": unidad,
            "valor": mejor[clave], "player_id": mejor["player_id"], "name": mejor["name"],
            "feb_code": mejor["feb_code"], "team": mejor["team"],
            "owner": duenos.get(mejor["player_id"]),
            # el resto de su línea, para que la cifra tenga contexto
            "linea": {k: mejor[k] for k in ("pts", "treb", "ast", "val")},
        })

    return {"jornada": j, "lideres": lideres, "partidos": len(partidos),
            "completa": completa, "faltan": faltan, "sin_acta": falta["sin_acta"]}


def directo(session: Session, league: FantasyLeague) -> dict:
    """Todo lo de la jornada que se está jugando, en vivo.

    Mientras se juega no se ficha, así que la pestaña del mercado no pinta nada: este es
    el sitio al que se viene a mirar. Trae la clasificación provisional de la jornada, el
    quinteto de cada uno con lo que lleva sumado, y los partidos con su marcador —solo los
    disputados: el resto figuran como pendientes aunque la base ya sepa cómo acaban.
    """
    st = league_state(session, league)
    j = st["jornada"]
    pts = jornada_points(session, league, j)
    info = {r["player_id"]: r for r in all_priced(session, league)}
    partidos = jornada_matches(session, league, j)

    # De qué partido es cada equipo esta jornada, para saber si un jugador ya ha jugado.
    equipos_jugados = set()
    for m in partidos:
        if m["home_score"] is not None:
            equipos_jugados.update([m["home_id"], m["away_id"]])

    filas = []
    for m in session.exec(select(FantasyMember)
                          .where(FantasyMember.league_id == league.id)).all():
        titulares = frozen_lineup(session, league, m.id, j)
        if titulares is None:
            titulares = [p.player_id for p in picks_of(session, m.id) if p.starter]
        jugadores = []
        for pid in titulares:
            d = info.get(pid, {})
            jugadores.append({
                "player_id": pid, "name": d.get("name"), "feb_code": d.get("feb_code"),
                "team": d.get("team"), "team_id": d.get("team_id"),
                # None SOLO si su partido no se ha jugado todavía. Si ya se jugó y no
                # aparece en los puntos es que no saltó a pista: eso es un cero de verdad,
                # y confundirlo con "está por jugar" da falsas esperanzas al que va perdiendo.
                "points": (pts.get(pid, 0.0)
                           if d.get("team_id") in equipos_jugados else None),
                "jugado": d.get("team_id") in equipos_jugados,
            })
        filas.append({
            "member_id": m.id, "manager": m.manager_name,
            "points": round(sum(pts.get(p["player_id"], 0.0) for p in jugadores), 1),
            "total_points": m.total_points,
            "por_jugar": sum(1 for p in jugadores if not p["jugado"]),
            "jugadores": jugadores,
        })

    filas.sort(key=lambda r: -r["points"])
    for i, r in enumerate(filas):
        r["pos"] = filas[i - 1]["pos"] if i and r["points"] == filas[i - 1]["points"] else i + 1

    sim = st.get("sim") or {}
    return {
        "jornada": j,
        "played": sim.get("played"), "total": sim.get("total"),
        "en_juego": st["phase"] == "jornada",
        "clasificacion": filas,
        "partidos": partidos,
    }


def jornada_ranking(session: Session, league: FantasyLeague, jornada: Optional[int] = None) -> dict:
    """Clasificación de UNA jornada: quién sumó más ese fin de semana.

    Es lo que convierte el acumulado en una carrera semanal: puedes ir décimo en la general
    y ganar la jornada. Sin `jornada` devuelve la última puntuada.
    """
    j = jornada if jornada is not None else league.current_jornada
    if j <= 0:
        return {"jornada": 0, "rows": [], "jornadas": []}
    rows = session.exec(
        select(FantasyJornadaScore, FantasyMember)
        .join(FantasyMember, FantasyMember.id == FantasyJornadaScore.member_id)
        .where(FantasyJornadaScore.league_id == league.id, FantasyJornadaScore.jornada == j)
    ).all()
    out = [{"member_id": m.id, "manager": m.manager_name, "points": sc.points,
            "score_id": sc.id,
            "starters": json.loads(sc.starters) if sc.starters else None} for sc, m in rows]
    out.sort(key=lambda r: -r["points"])
    for i, r in enumerate(out):
        # mismos puntos, mismo puesto
        r["pos"] = out[i - 1]["pos"] if i and r["points"] == out[i - 1]["points"] else i + 1

    # Cómo lo hizo cada jugador esa jornada, con el quinteto que estaba puesto ENTONCES.
    #
    # Las jornadas puntuadas antes de que se guardara ese quinteto no tienen forma de
    # saberlo, y reconstruirlo con la plantilla de hoy era peor que no decir nada: cada vez
    # que alguien tocaba su alineación, el pasado cambiaba. En esas se marca
    # `lineup_known: false` y la app enseña la plantilla sin repartir titulares.
    if out:
        pts = jornada_points(session, league, j)
        info = {r["player_id"]: r for r in all_priced(session, league)}
        descansan = resting_teams(session, league, j)
        # Equipos cuyo partido de esa jornada está aún por disputarse (o sin acta): sus
        # jugadores marcan cero, pero no es lo mismo que no haber jugado y decirlo mal es
        # justo lo que hace pensar que la app se ha comido unos puntos.
        pendientes = _equipos_pendientes(session, league, j)
        recuperadas = False
        for r in out:
            picks = picks_of(session, r["member_id"])
            saved = r.pop("starters")
            score_id = r.pop("score_id")
            if saved is None:
                # jornada anterior a que se guardara el quinteto: se deduce del total y se
                # deja escrito, para que a partir de ahora sea historia y no un cálculo
                saved = _recover_starters(league, picks, pts, r["points"], j)
                if saved is not None:
                    sc = session.get(FantasyJornadaScore, score_id)
                    sc.starters = json.dumps(saved)
                    session.add(sc)
                    recuperadas = True
            r["lineup_known"] = saved is not None
            if saved is not None:
                # los que jugaron esa jornada aunque ya no estén en la plantilla, primero
                ids = list(saved) + [p.player_id for p in picks if p.player_id not in saved]
            else:
                # al menos se quitan los que se ficharon DESPUÉS: esos seguro que no estaban
                ids = [p.player_id for p in picks if p.buy_jornada <= j]
            players = []
            for pid in ids:
                d = info.get(pid, {})
                players.append({
                    "player_id": pid, "name": d.get("name", "?"),
                    "feb_code": d.get("feb_code"), "team": d.get("team"),
                    "points": pts.get(pid, 0.0), "played": pid in pts,
                    # cero por descanso de calendario, no por quedarse en el banquillo
                    "rests": pid not in pts and d.get("team_id") in descansan,
                    # su partido todavía no se ha jugado: el cero es provisional
                    "pending": pid not in pts and d.get("team_id") in pendientes,
                    "starter": bool(saved is not None and pid in saved),
                    # ya no lo tienes: se enseña igual, pero se avisa
                    "gone": pid not in {p.player_id for p in picks},
                })
            players.sort(key=lambda x: (not x["starter"], -x["points"]))
            r["players"] = players
        if recuperadas:
            session.commit()

    todas = session.exec(select(FantasyJornadaScore).where(
        FantasyJornadaScore.league_id == league.id)).all()
    js = sorted({s_.jornada for s_ in todas})
    # Si a esta jornada le falta algún partido, sus puntos son provisionales: se dice, para
    # que quien la mire entienda por qué su posición puede moverse sola.
    falta = (jornada_falta(session, league, j)
             if any(s_.jornada == j and not s_.complete for s_ in todas)
             else {"faltan": [], "sin_acta": [], "completa": True})
    return {"jornada": j, "rows": out, "jornadas": js, "completa": falta["completa"],
            "faltan": falta["faltan"], "sin_acta": falta["sin_acta"]}


def standings(session: Session, league: FantasyLeague) -> list[dict]:
    prices = price_map(session, league)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    rows = []
    for m in members:
        picks = picks_of(session, m.id)
        value = round(sum(prices.get(p.player_id, 0.0) for p in picks), 1)
        rows.append({
            "member_id": m.id, "user_id": m.user_id, "manager": m.manager_name,
            "total_points": m.total_points, "budget_remaining": m.budget_remaining,
            "squad_value": value, "worth": round(value + m.budget_remaining, 1),
            "squad_count": len(picks),
        })
    rows.sort(key=lambda r: (-r["total_points"], -r["worth"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def mi_marcador(session: Session, league: FantasyLeague,
                member: Optional[FantasyMember]) -> Optional[dict]:
    """Dónde vas: puesto, puntos, a cuánto tienes al de delante y cómo va tu racha.

    Es lo primero que se quiere saber al abrir la liga y hasta ahora no estaba en ninguna
    parte de esa pantalla: había que irse a la pestaña de clasificación a buscarlo. El
    puesto de cada jornada se reconstruye acumulando los desgloses, que es la única forma
    de poder decir "has subido dos puestos" sin guardar nada más.
    """
    if not member:
        return None
    scores = session.exec(select(FantasyJornadaScore).where(
        FantasyJornadaScore.league_id == league.id)).all()
    miembros = {m.id: m.manager_name for m in _members(session, league.id)}

    # acumulado por jornada -> puesto de cada uno en cada momento
    jornadas = sorted({sc.jornada for sc in scores})
    acumulado: dict[int, float] = {mid: 0.0 for mid in miembros}
    puestos: list[dict[int, int]] = []
    mios: list[dict] = []
    for j in jornadas:
        for sc in scores:
            if sc.jornada == j:
                acumulado[sc.member_id] = round(acumulado.get(sc.member_id, 0.0) + sc.points, 1)
        orden = sorted(acumulado.items(), key=lambda kv: -kv[1])
        tabla, ant = {}, None
        for i, (mid, pts) in enumerate(orden):
            tabla[mid] = tabla[orden[i - 1][0]] if i and pts == ant else i + 1
            ant = pts
        puestos.append(tabla)
        sc_mio = next((x for x in scores if x.jornada == j and x.member_id == member.id), None)
        if sc_mio:
            mios.append({"jornada": j, "points": sc_mio.points,
                         "complete": sc_mio.complete, "pos": tabla.get(member.id)})

    orden = sorted(miembros, key=lambda mid: -acumulado.get(mid, 0.0))
    pos = (puestos[-1].get(member.id) if puestos else None) or 1
    delta = None
    if len(puestos) >= 2 and puestos[-2].get(member.id) and puestos[-1].get(member.id):
        delta = puestos[-2][member.id] - puestos[-1][member.id]   # positivo = has subido

    # el de delante: a quién persigues. Si vas primero, a quién le sacas ventaja.
    yo = orden.index(member.id) if member.id in orden else 0
    vecino = orden[yo - 1] if yo > 0 else (orden[1] if len(orden) > 1 else None)
    hueco = None
    if vecino is not None:
        hueco = round(abs(acumulado.get(vecino, 0.0) - acumulado.get(member.id, 0.0)), 1)

    return {
        "pos": pos, "de": len(miembros), "points": round(acumulado.get(member.id, 0.0), 1),
        "lider": yo == 0,
        "rival": miembros.get(vecino) if vecino is not None else None,
        "gap": hueco,
        "delta_pos": delta,
        "jugadas": len(mios),
        # las últimas ocho, que es lo que cabe sin que la tira se vuelva ilegible
        "racha": mios[-8:],
    }


def my_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> list[dict]:
    # all_priced ya trae nombre, equipo y stats, así que no hace falta volver a recorrer
    # los boxscores con conference_games ni pedir el price_map por separado.
    info = {r["player_id"]: r for r in all_priced(session, league)}
    out = []
    now = utcnow()
    # el que descansa esta jornada sumará cero haga lo que haga: mejor saberlo antes de
    # cerrar el quinteto que después, mirando el desglose
    st = league_state(session, league)
    descansan = resting_teams(session, league, st["jornada"])
    # Con la jornada en juego, lo que importa no es la media de la temporada sino lo que tu
    # quinteto está sumando AHORA. Va aparte para que la app cambie el número grande sin
    # perder la media, que se sigue queriendo saber al fichar.
    en_juego = st["phase"] == "jornada"
    vivos = jornada_points(session, league, st["jornada"]) if en_juego else {}
    # Los que ya han jugado su partido de esta jornada: su sitio está cerrado aunque la
    # liga siga en mercado (partido adelantado). La app los pinta con candado, para que se
    # entienda antes de intentar moverlos.
    sellados = sellados_de(session, league, member.id, st["jornada"])
    jugando = equipos_en_juego(session, league, st["jornada"]) if st.get("adelanto") else {}
    jugados_eq: set = set()
    if en_juego:
        for mm in jornada_matches(session, league, st["jornada"]):
            if mm["home_score"] is not None:
                jugados_eq.update([mm["home_id"], mm["away_id"]])
    for p in picks_of(session, member.id):
        d = info.get(p.player_id, {})
        cur = d.get("price", p.buy_price)
        locked = bool(p.clause_locked_until and now < p.clause_locked_until)
        out.append({
            "player_id": p.player_id, "name": d.get("name", "?"), "feb_code": d.get("feb_code"),
            "team": d.get("team"), "team_id": d.get("team_id"),
            "rests": d.get("team_id") in descansan,
            "buy_price": p.buy_price, "price": cur,
            "delta": round(cur - p.buy_price, 1), "starter": p.starter,
            "val_avg": d.get("val_avg", 0), "form": d.get("form", 0),
            "fp_avg": d.get("fp_avg", 0), "fp_form": d.get("fp_form", 0),
            "games": d.get("games", 0),
            # puntos de la jornada en curso: None mientras su partido no se haya jugado
            "live_fp": (vivos.get(p.player_id, 0.0)
                        if en_juego and d.get("team_id") in jugados_eq else None),
            "live": en_juego,
            # puesto en venta: la liga le va mandando ofertas
            "on_sale": bool(p.sale_started_at),
            "sale_offers_made": p.sale_offers_made,
            # fichó por otro equipo: sigue en tu plantilla pero ya no puntúa
            "departed": bool(d.get("departed")),
            # su partido de esta jornada ya se ha jugado: ni entra ni sale del quinteto
            "played_already": bool(p.player_id in sellados or d.get("team_id") in jugando),
            "sealed_starter": sellados.get(p.player_id),
            "clause": p.clause, "clause_locked": locked,
            "clause_lock_mins": int((p.clause_locked_until - now).total_seconds() // 60) if locked else 0,
        })
    out.sort(key=lambda r: (not r["starter"], -r["price"]))
    return out


def adelanto_info(session: Session, league: FantasyLeague,
                  member: Optional[FantasyMember]) -> Optional[dict]:
    """El partido (o partidos) que se juegan por delante del resto de la jornada, y a
    quién de tu plantilla le afectan. None si no hay ninguno.

    Es lo que la app enseña al entrar: la liga no se para por un adelanto, pero sí hay que
    avisar, porque a esos jugadores ya no se les puede mover. Quien no haga nada se queda
    con el quinteto que tuviera puesto, que es lo que se sella.
    """
    st = league_state(session, league)
    if not st.get("adelanto") or st["phase"] == "jornada":
        return None
    j = st["jornada"]
    jugando = equipos_en_juego(session, league, j)
    if not jugando:
        return None
    partidos = [r for r in jornada_matches(session, league, j)
                if r["home_id"] in jugando or r["away_id"] in jugando]
    mios = []
    if member:
        sellados = sellados_de(session, league, member.id, j)
        info = {r["player_id"]: r for r in all_priced(session, league)}
        for p in picks_of(session, member.id):
            d = info.get(p.player_id, {})
            if d.get("team_id") not in jugando:
                continue
            mios.append({
                "player_id": p.player_id, "name": d.get("name", "?"),
                "feb_code": d.get("feb_code"), "team": d.get("team"),
                "starter": sellados.get(p.player_id, p.starter),
                "sealed": p.player_id in sellados,
                "fp_avg": d.get("fp_avg", 0),
            })
    return {"jornada": j, "matches": partidos, "players": mios,
            "kickoff_at": _iso(st["kickoff_at"]),
            "market_deadline": _iso(st["market_deadline"])}


def feed(session: Session, league_id: int, limit: int = 40) -> list[dict]:
    rows = session.exec(select(FantasyEvent).where(FantasyEvent.league_id == league_id)
                        .order_by(FantasyEvent.id.desc()).limit(limit)).all()
    return [{"id": e.id, "kind": e.kind, "text": e.text,
             "at": e.created_at.isoformat() + "Z"} for e in rows]



def notifications(session: Session, user_id: int, limit: int = 40,
                  league_id: Optional[int] = None) -> dict:
    """Los últimos avisos del usuario y cuántos lleva sin leer.

    Con `league_id`, solo los de esa liga: quien juega en dos no quiere ver dentro de
    una lo que le ha pasado en la otra (ni que el contador se lo cuente).
    """
    def suyos():
        q = select(FantasyNotification).where(FantasyNotification.user_id == user_id)
        return q if league_id is None else q.where(
            FantasyNotification.league_id == league_id)

    rows = session.exec(suyos()
                        .order_by(FantasyNotification.id.desc()).limit(limit)).all()
    unread = len(session.exec(
        suyos().where(FantasyNotification.read == False)).all())  # noqa: E712
    names: dict[int, str] = {}
    items = []
    for n in rows:
        if n.league_id not in names:
            lg = session.get(FantasyLeague, n.league_id)
            names[n.league_id] = lg.name if lg else ""
        items.append({"id": n.id, "league_id": n.league_id, "league": names[n.league_id],
                      "kind": n.kind, "title": n.title, "body": n.body, "read": n.read,
                      "at": n.created_at.isoformat() + "Z"})
    return {"items": items, "unread": unread}


def mark_notifications_read(session: Session, user_id: int,
                            league_id: Optional[int] = None) -> dict:
    """Marca leídos. Con `league_id`, solo los de esa liga: si abres la campana dentro
    de una, los avisos de las otras te siguen esperando allí."""
    q = select(FantasyNotification).where(
        FantasyNotification.user_id == user_id,
        FantasyNotification.read == False)  # noqa: E712
    if league_id is not None:
        q = q.where(FantasyNotification.league_id == league_id)
    rows = session.exec(q).all()
    for n in rows:
        n.read = True
        session.add(n)
    session.commit()
    return {"ok": True, "read": len(rows)}


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def league_out(league: FantasyLeague, state: Optional[dict] = None) -> dict:
    """Datos de la liga para la app. Con `state` (de `league_state`) viaja además la fase:
    es lo que la web usa para saber si se puede pujar, vender o tocar el quinteto."""
    extra = {}
    if state:
        extra = {
            "phase": state["phase"], "next_jornada": state["jornada"],
            "phase_until": _iso(state["until"]),
            "kickoff_at": _iso(state["kickoff_at"]),
            "jornada_ends_at": _iso(state["ends_at"]),
            "market_deadline": _iso(state["market_deadline"]),
            "pending_matches": state["pending"],
            # hay un partido de la jornada que se juega por delante del resto: la liga
            # sigue igual, pero conviene decirlo y ofrecer confirmar el quinteto
            "adelanto": bool(state.get("adelanto")),
            "first_kickoff": _iso(state.get("first_kickoff")),
            # atajos para la UI: qué está bloqueado ahora mismo
            "can_trade": state["phase"] == "mercado",
            "can_lineup": state["phase"] in ("mercado", "alineacion"),
            # en simulación, en qué paso va la jornada y cuántos partidos llevan jugados
            "sim": state.get("sim"),
            "sim_incidencias": league.sim_incidencias,
        }
    return {**extra, **{
        "id": league.id, "name": league.name, "join_code": league.join_code,
        "owner_user_id": league.owner_user_id, "competition": league.competition,
        "grupo": league.grupo, "season": league.season, "budget": league.budget,
        "squad_size": league.squad_size, "lineup_size": league.lineup_size,
        "win_bonus": league.win_bonus, "start_jornada": league.start_jornada,
        "current_jornada": league.current_jornada, "max_jornada": league.max_jornada,
        "market_weekday": league.market_weekday, "market_hour": league.market_hour,
        "market_weekday_name": "todos los días", "market_daily": True,
        "market_duration_h": league.market_duration_h, "market_size": league.market_size,
        "market_open": league.market_open, "market_round": league.market_round,
        "market_opens_at": _iso(league.market_opens_at),
        "market_closes_at": _iso(league.market_closes_at),
        "clause_factor": league.clause_factor, "clause_lock_h": league.clause_lock_h,
        "clause_raise_cost": league.clause_raise_cost,
        "sim_mode": league.sim_mode, "play_weekday": league.play_weekday,
        "play_weekday_name": WEEKDAYS[league.play_weekday % 7], "play_hour": league.play_hour,
        "play_duration_h": league.play_duration_h,
        "market_close_before_h": league.market_close_before_h,
    }}
