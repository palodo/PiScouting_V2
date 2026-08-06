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
    FantasyJornadaScore,
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
    """player_id -> {name, feb_code, team_id, team, games:[{j,val,pm,won}]} ordenado por jornada."""
    # Se piden columnas sueltas y no entidades: con objetos del ORM, 3ª FEB (unas 40.000
    # líneas de boxscore) llegaba a 247 MB de pico, y el plan gratuito de Render tiene 512.
    q = (
        select(Player.id, Player.name, Player.feb_code, Team.id, Team.name,
               Match.jornada_num, Match.home_score, Match.away_score,
               PlayerMatchStat.is_home, PlayerMatchStat.val, PlayerMatchStat.plus_minus)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(Team.competition == comp, Team.season == season)
    )
    if grupo:
        q = q.where(Team.grupo == grupo)
    out: dict[int, dict] = {}
    for (pid, pname, feb_code, tid, tname, jornada_num,
         home_score, away_score, is_home, val, pm) in session.exec(q):
        if jornada_num is None:
            continue
        my = home_score if is_home else away_score
        opp = away_score if is_home else home_score
        won = my is not None and opp is not None and my > opp
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
        d["games"].append({"j": jornada_num, "val": val, "pm": pm, "won": won})
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


def _fp(game: dict, win_bonus: float) -> float:
    """Puntos fantasy de UN partido: valoración + bonus si su equipo ganó."""
    return game["val"] + (win_bonus if game["won"] else 0.0)


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


def jornada_dates(session: Session, league: FantasyLeague, jornada: int) -> tuple:
    """(primera, última) fecha de los partidos de esa jornada. (None, None) si no hay."""
    q = select(Match.match_date).where(Match.competition == league.competition,
                                       Match.season == league.season,
                                       Match.jornada_num == jornada)
    if league.grupo:
        q = q.where(Match.grupo == league.grupo)
    days = [d for d in session.exec(q).all() if d]
    return (min(days), max(days)) if days else (None, None)


def _first_kickoff(league: FantasyLeague, now: datetime) -> datetime:
    """Primer salto de la primera jornada de la liga: el próximo día de partido que deje
    tiempo de mercado por delante (si no, la liga nacería con el mercado ya cerrado)."""
    margin = timedelta(hours=league.market_close_before_h + 12)
    return _weekly_slot(now + margin, league.play_weekday, league.play_hour)


def jornada_window(session: Session, league: FantasyLeague, jornada: int) -> tuple:
    """(primer salto, final previsto) de una jornada, en UTC naive.

    Con la temporada en marcha manda el calendario real de la FEB (que además absorbe los
    aplazamientos: si un partido se mueve, la jornada acaba más tarde). En simulación —o si
    esa jornada no tiene fechas— manda el calendario semanal de la liga.
    """
    if not league.sim_mode:
        first, last = jornada_dates(session, league, jornada)
        if first:
            # La FEB solo nos da el día, no la hora: se usa la hora de partido de la liga.
            return _at(first, league.play_hour), _at(last, 23, 59)
    start = league.kickoff_at or _first_kickoff(league, utcnow())
    return start, start + timedelta(hours=league.play_duration_h)


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

    kickoff, ends = jornada_window(session, league, nxt)
    deadline = kickoff - timedelta(hours=league.market_close_before_h)
    pending: list[str] = []
    if now < deadline:
        phase, until = "mercado", deadline
    elif now < kickoff:
        phase, until = "alineacion", kickoff
    else:
        # La jornada no se da por terminada mientras le falte algún partido por jugarse:
        # así un aplazamiento no deja a nadie con un cero que no le toca.
        phase, until = "jornada", ends
        pending = pending_matches(session, league, nxt)
    return {"phase": phase, "jornada": nxt, "kickoff_at": kickoff, "ends_at": ends,
            "market_deadline": deadline, "until": until, "pending": pending}


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


def _log(session: Session, league_id: int, kind: str, text: str) -> None:
    session.add(FantasyEvent(league_id=league_id, kind=kind, text=text))


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
            pl = session.get(Player, lst.player_id)
            _log(session, league.id, "signing",
                 f"✍️ {m.manager_name} ficha a {pl.name if pl else '?'} por {b.amount} M€")
            session.add_all([b, m])
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

        if phase == "jornada":
            # Jugada entera (y sin aplazamientos pendientes): se puntúa sola.
            if now >= state["ends_at"] and not state["pending"] and advance(session, league).get("ok"):
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
                if state["market_deadline"] - now >= timedelta(hours=1) \
                        and _open_round(session, league, now, state["market_deadline"]):
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
def jornada_points(session: Session, league: FantasyLeague, jornada: int) -> dict[int, float]:
    conf = conference_games(session, league.competition, league.grupo, league.season)
    out: dict[int, float] = {}
    for pid, d in conf.items():
        games = [g for g in d["games"] if g["j"] == jornada]
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
                  market_duration_h: int = 24, market_size: int = 10,
                  initial_squad: int = 5, clause_factor: float = 2.0,
                  clause_lock_h: int = 24, open_now: bool = True,
                  sim_mode: bool = True, play_weekday: int = 5, play_hour: int = 18,
                  play_duration_h: int = 30,
                  market_close_before_h: int = 24) -> FantasyLeague:
    if competition not in FANTASY_COMPETITIONS:
        raise ValueError("Esa competición no está disponible para el fantasy.")
    mj = max_jornada(session, competition, grupo, season)
    if mj == 0:
        raise ValueError("Esa conferencia no tiene datos de partidos todavía")
    start = start_jornada if start_jornada is not None else max(3, round(mj * 0.35))
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
        sim_mode=bool(sim_mode),
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
    _log(session, league.id, "info",
         f"🏆 Liga creada · jornada los {WEEKDAYS[league.play_weekday]} a las "
         f"{league.play_hour:02d}:00 · mercado todos los días a las {league.market_hour:02d}:00 "
         f"hasta {league.market_close_before_h} h antes")
    session.commit()
    join_league(session, league, owner_id, manager_name)
    sync_market(session, league)
    return league


def _assign_initial_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> None:
    """Plantilla inicial aleatoria para poder jugar desde el primer momento."""
    if league.initial_squad <= 0:
        return
    owned = owned_player_ids(session, league.id)
    pool = [r for r in all_priced(session, league) if r["player_id"] not in owned]
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


def committed_amount(session: Session, member_id: int) -> float:
    bids = session.exec(select(FantasyBid).where(
        FantasyBid.member_id == member_id, FantasyBid.status == "active")).all()
    return round(sum(b.amount for b in bids), 1)


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
    _log(session, league.id, "clause",
         f"💥 CLAUSULAZO · {member.manager_name} se lleva a {pl.name if pl else '?'} "
         f"de {owner.manager_name} por {amount} M€")
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
def player_detail(session: Session, league: FantasyLeague, player_id: int) -> dict:
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
        games.append({"j": m.jornada_num, "val": st.val, "pts": st.pts, "reb": st.treb,
                      "ast": st.ast, "pm": st.plus_minus, "min": round(st.seconds / 60, 1),
                      "won": won})
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
    }


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


def sell(session: Session, league: FantasyLeague, member: FantasyMember, player_id: int) -> dict:
    sync_market(session, league)
    _require(session, league, "mercado", what="podrás vender")
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    price = price_map(session, league).get(player_id, pick.buy_price)
    member.budget_remaining = round(member.budget_remaining + price, 1)
    session.delete(pick)
    session.add(member)
    pl = session.get(Player, player_id)
    _log(session, league.id, "sale", f"💸 {member.manager_name} vende a {pl.name if pl else '?'} por {price} M€")
    session.commit()
    return {"ok": True, "price": price, "budget_remaining": member.budget_remaining}


def set_lineup(session: Session, league: FantasyLeague, member: FantasyMember,
               starter_ids: list[int]) -> dict:
    sync_market(session, league)
    # El quinteto se puede tocar hasta el primer salto: es lo último que se cierra.
    _require(session, league, "mercado", "alineacion", what="podrás cambiar el quinteto")
    if len(starter_ids) > league.lineup_size:
        raise ValueError(f"Solo puedes alinear {league.lineup_size} titulares")
    picks = picks_of(session, member.id)
    if not set(starter_ids).issubset({p.player_id for p in picks}):
        raise ValueError("Algún titular no está en tu plantilla")
    for p in picks:
        p.starter = p.player_id in starter_ids
        session.add(p)
    session.commit()
    return {"ok": True, "starters": starter_ids}


# ============================ jornada / clasificación ============================
def pending_matches(session: Session, league: FantasyLeague, jornada: int) -> list[str]:
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
        if m.home_score is None or m.away_score is None:
            local = session.get(Team, m.home_team_id) if m.home_team_id else None
            visit = session.get(Team, m.away_team_id) if m.away_team_id else None
            faltan.append(f"{local.name if local else '?'} - {visit.name if visit else '?'}")
    return faltan


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


def advance(session: Session, league: FantasyLeague) -> dict:
    if league.current_jornada >= league.max_jornada:
        return {"ok": False, "done": True, "message": "La temporada ya está completa"}
    nxt = league.current_jornada + 1
    faltan = pending_matches(session, league, nxt)
    if faltan:
        return {"ok": False, "pending": faltan, "jornada": nxt,
                "message": (f"La jornada {nxt} no está completa: falta por jugarse "
                            + (f"{faltan[0]}" if len(faltan) == 1 else f"{len(faltan)} partidos")
                            + ". Se puntuará cuando se dispute.")}
    pts = jornada_points(session, league, nxt)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    breakdown = []
    for m in members:
        starters = [p.player_id for p in picks_of(session, m.id) if p.starter]
        gained = round(sum(pts.get(pid, 0.0) for pid in starters), 1)
        m.total_points = round(m.total_points + gained, 1)
        session.add(m)
        # se guarda el desglose (con el quinteto de ESE momento): en el miembro solo queda
        # el acumulado, y la plantilla cambiará antes de que nadie mire atrás
        session.add(FantasyJornadaScore(league_id=league.id, member_id=m.id, jornada=nxt,
                                        points=gained, starters=json.dumps(starters)))
        breakdown.append({"member_id": m.id, "manager": m.manager_name, "gained": gained})
    league.current_jornada = nxt
    _after_jornada(session, league)
    session.add(league)
    best = max(breakdown, key=lambda b: b["gained"], default=None)
    _log(session, league.id, "jornada",
         f"📅 Jornada {nxt} puntuada" + (f" · mejor: {best['manager']} ({best['gained']} pts)" if best else ""))
    session.commit()
    return {"ok": True, "jornada": nxt, "breakdown": breakdown,
            "done": league.current_jornada >= league.max_jornada}


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
            "starters": json.loads(sc.starters) if sc.starters else None} for sc, m in rows]
    out.sort(key=lambda r: -r["points"])
    for i, r in enumerate(out):
        # mismos puntos, mismo puesto
        r["pos"] = out[i - 1]["pos"] if i and r["points"] == out[i - 1]["points"] else i + 1

    # Cómo lo hizo cada jugador esa jornada, con el quinteto que estaba puesto entonces
    # (las jornadas puntuadas antes de guardarlo caen en la plantilla actual, como antes).
    if out:
        pts = jornada_points(session, league, j)
        info = {r["player_id"]: r for r in all_priced(session, league)}
        for r in out:
            picks = picks_of(session, r["member_id"])
            saved = r.pop("starters")
            # los que jugaron esa jornada aunque ya no estén en la plantilla, primero
            ids = list(saved or []) + [p.player_id for p in picks
                                       if p.player_id not in (saved or [])]
            was_starter = ((lambda pid: pid in saved) if saved is not None
                           else (lambda pid: any(p.starter for p in picks if p.player_id == pid)))
            players = []
            for pid in ids:
                d = info.get(pid, {})
                players.append({
                    "player_id": pid, "name": d.get("name", "?"),
                    "feb_code": d.get("feb_code"), "team": d.get("team"),
                    "points": pts.get(pid, 0.0), "played": pid in pts,
                    "starter": was_starter(pid),
                    # ya no lo tienes: se enseña igual, pero se avisa
                    "gone": pid not in {p.player_id for p in picks},
                })
            players.sort(key=lambda x: (not x["starter"], -x["points"]))
            r["players"] = players

    js = sorted({s_.jornada for s_ in session.exec(
        select(FantasyJornadaScore).where(FantasyJornadaScore.league_id == league.id)).all()})
    return {"jornada": j, "rows": out, "jornadas": js}


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


def my_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> list[dict]:
    # all_priced ya trae nombre, equipo y stats, así que no hace falta volver a recorrer
    # los boxscores con conference_games ni pedir el price_map por separado.
    info = {r["player_id"]: r for r in all_priced(session, league)}
    out = []
    now = utcnow()
    for p in picks_of(session, member.id):
        d = info.get(p.player_id, {})
        cur = d.get("price", p.buy_price)
        locked = bool(p.clause_locked_until and now < p.clause_locked_until)
        out.append({
            "player_id": p.player_id, "name": d.get("name", "?"), "feb_code": d.get("feb_code"),
            "team": d.get("team"), "buy_price": p.buy_price, "price": cur,
            "delta": round(cur - p.buy_price, 1), "starter": p.starter,
            "val_avg": d.get("val_avg", 0), "form": d.get("form", 0),
            "fp_avg": d.get("fp_avg", 0), "fp_form": d.get("fp_form", 0),
            "games": d.get("games", 0),
            # fichó por otro equipo: sigue en tu plantilla pero ya no puntúa
            "departed": bool(d.get("departed")),
            "clause": p.clause, "clause_locked": locked,
            "clause_lock_mins": int((p.clause_locked_until - now).total_seconds() // 60) if locked else 0,
        })
    out.sort(key=lambda r: (not r["starter"], -r["price"]))
    return out


def feed(session: Session, league_id: int, limit: int = 40) -> list[dict]:
    rows = session.exec(select(FantasyEvent).where(FantasyEvent.league_id == league_id)
                        .order_by(FantasyEvent.id.desc()).limit(limit)).all()
    return [{"id": e.id, "kind": e.kind, "text": e.text,
             "at": e.created_at.isoformat() + "Z"} for e in rows]


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
            # atajos para la UI: qué está bloqueado ahora mismo
            "can_trade": state["phase"] == "mercado",
            "can_lineup": state["phase"] in ("mercado", "alineacion"),
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
