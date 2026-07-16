"""Fantasy FEB — ligas por conferencia (competición + grupo).

Modelo de valoración: el precio de un jugador es DINÁMICO y se calcula sobre la marcha a
partir de sus estadísticas acumuladas hasta la jornada actual de la liga, mezclando su
valoración media (VAL), su forma reciente y su +/-, y penalizando muestras pequeñas
(pocos partidos). Al arrancar la liga los precios reflejan la temporada hasta el corte;
según avanza el modo repetición, los precios suben y bajan con el rendimiento.

Puntuación por jornada: VAL del jugador + bonus si su equipo ganó ese partido.
"""
from __future__ import annotations

import random
import string
from typing import Optional

from sqlmodel import Session, select

from .config import FANTASY_COMPETITIONS
from .models import (
    Team, Player, Match, PlayerMatchStat,
    FantasyLeague, FantasyMember, FantasyPick,
)

# --- parámetros del modelo de precio ---
PRICE_K = 1.1
PRICE_MIN = 3.0
PRICE_MAX = 25.0
RECENT_N = 4  # partidos para la "forma reciente"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ============================ datos de la conferencia ============================
def conference_games(session: Session, comp: str, grupo: Optional[str], season: str) -> dict:
    """player_id -> {name, feb_code, team_id, team, games: [{j, val, pm, won}] ordenado por jornada}."""
    q = (
        select(PlayerMatchStat, Match, Player, Team)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(Team.competition == comp, Team.season == season)
    )
    if grupo:
        q = q.where(Team.grupo == grupo)
    out: dict[int, dict] = {}
    for st, m, pl, tm in session.exec(q).all():
        if m.jornada_num is None:
            continue
        is_home = st.is_home
        my = m.home_score if is_home else m.away_score
        opp = m.away_score if is_home else m.home_score
        won = my is not None and opp is not None and my > opp
        d = out.setdefault(pl.id, {
            "player_id": pl.id, "name": pl.name, "feb_code": pl.feb_code,
            "team_id": tm.id, "team": tm.name, "games": [],
        })
        d["games"].append({"j": m.jornada_num, "val": st.val, "pm": st.plus_minus, "won": won})
    for d in out.values():
        d["games"].sort(key=lambda g: g["j"])
    return out


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
    price = PRICE_K * raw * (0.5 + 0.5 * reliab)
    return round(_clamp(price, PRICE_MIN, PRICE_MAX), 1)


MARKET_SIZE = 24  # jugadores que se ofertan en el mercado cada jornada


def _all_priced(session: Session, league: FantasyLeague) -> list[dict]:
    """Todos los jugadores de la conferencia con su precio actual y stats (base del mercado
    y del valor de plantilla)."""
    conf = conference_games(session, league.competition, league.grupo, league.season)
    # partidos jugados por equipo hasta la jornada actual (para la fiabilidad)
    team_games: dict[int, int] = {}
    for d in conf.values():
        tg = len([g for g in d["games"] if g["j"] <= league.current_jornada])
        team_games[d["team_id"]] = max(team_games.get(d["team_id"], 0), tg)
    rows = []
    for d in conf.values():
        played = [g for g in d["games"] if g["j"] <= league.current_jornada]
        if not played:
            continue
        price = _price_from_games(d["games"], league.current_jornada, team_games.get(d["team_id"], 1))
        n = len(played)
        rows.append({
            "player_id": d["player_id"], "name": d["name"], "feb_code": d["feb_code"],
            "team_id": d["team_id"], "team": d["team"], "price": price, "games": n,
            "val_avg": round(sum(g["val"] for g in played) / n, 1),
            "pm_avg": round(sum(g["pm"] for g in played) / n, 1),
            "form": round(sum(g["val"] for g in played[-RECENT_N:]) / len(played[-RECENT_N:]), 1),
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    return rows


def owned_player_ids(session: Session, league_id: int) -> set[int]:
    """Jugadores ya fichados por CUALQUIER mánager de la liga (ownership exclusivo)."""
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league_id)).all()
    mids = [m.id for m in members]
    if not mids:
        return set()
    picks = session.exec(select(FantasyPick).where(FantasyPick.member_id.in_(mids))).all()
    return {p.player_id for p in picks}


def market(session: Session, league: FantasyLeague) -> list[dict]:
    """Mercado de la jornada: subconjunto ALEATORIO de jugadores LIBRES (no fichados por nadie).
    Rota cada jornada con semilla estable (misma oferta para todos los mánagers dentro de la
    jornada) y crea escasez: cada jugador solo puede tenerlo un mánager."""
    owned = owned_player_ids(session, league.id)
    pool = [r for r in _all_priced(session, league) if r["player_id"] not in owned]
    rng = random.Random(f"{league.id}:{league.current_jornada}")
    rng.shuffle(pool)
    return pool[:MARKET_SIZE]


def price_map(session: Session, league: FantasyLeague) -> dict[int, float]:
    return {r["player_id"]: r["price"] for r in _all_priced(session, league)}


# ============================ puntuación por jornada ============================
def jornada_points(session: Session, league: FantasyLeague, jornada: int) -> dict[int, float]:
    """player_id -> puntos fantasy en esa jornada (VAL + bonus victoria)."""
    conf = conference_games(session, league.competition, league.grupo, league.season)
    out: dict[int, float] = {}
    for pid, d in conf.items():
        pts = 0.0
        for g in d["games"]:
            if g["j"] == jornada:
                pts += g["val"] + (league.win_bonus if g["won"] else 0.0)
        if any(g["j"] == jornada for g in d["games"]):
            out[pid] = round(pts, 1)
    return out


# ============================ operaciones de liga ============================
def _code(session: Session) -> str:
    while True:
        c = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not session.exec(select(FantasyLeague).where(FantasyLeague.join_code == c)).first():
            return c


def create_league(session: Session, owner_id: int, name: str, competition: str,
                  grupo: Optional[str], season: str, manager_name: str,
                  budget: float = 100.0, squad_size: int = 10, lineup_size: int = 5,
                  win_bonus: float = 4.0, start_jornada: Optional[int] = None) -> FantasyLeague:
    if competition not in FANTASY_COMPETITIONS:
        raise ValueError("Esa competición no está disponible para el fantasy.")
    mj = max_jornada(session, competition, grupo, season)
    if mj == 0:
        raise ValueError("Esa conferencia no tiene datos de partidos todavía")
    start = start_jornada if start_jornada is not None else max(3, round(mj * 0.35))
    start = _clamp(start, 1, mj - 1)
    league = FantasyLeague(
        name=name, join_code=_code(session), owner_user_id=owner_id, season=season,
        competition=competition, grupo=grupo, budget=budget, squad_size=squad_size,
        lineup_size=lineup_size, win_bonus=win_bonus, start_jornada=start,
        current_jornada=start, max_jornada=mj,
    )
    session.add(league)
    session.commit()
    session.refresh(league)
    join_league(session, league, owner_id, manager_name)
    return league


def join_league(session: Session, league: FantasyLeague, user_id: int, manager_name: str) -> FantasyMember:
    existing = session.exec(
        select(FantasyMember).where(FantasyMember.league_id == league.id,
                                    FantasyMember.user_id == user_id)
    ).first()
    if existing:
        return existing
    m = FantasyMember(league_id=league.id, user_id=user_id, manager_name=manager_name,
                      budget_remaining=league.budget)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def member_of(session: Session, league_id: int, user_id: int) -> Optional[FantasyMember]:
    return session.exec(
        select(FantasyMember).where(FantasyMember.league_id == league_id,
                                    FantasyMember.user_id == user_id)
    ).first()


def picks_of(session: Session, member_id: int) -> list[FantasyPick]:
    return session.exec(select(FantasyPick).where(FantasyPick.member_id == member_id)).all()


def buy(session: Session, league: FantasyLeague, member: FantasyMember, player_id: int) -> dict:
    picks = picks_of(session, member.id)
    if any(p.player_id == player_id for p in picks):
        raise ValueError("Ya tienes a ese jugador")
    if len(picks) >= league.squad_size:
        raise ValueError(f"Plantilla llena ({league.squad_size} jugadores)")
    if player_id in owned_player_ids(session, league.id):
        raise ValueError("Ese jugador ya lo tiene otro mánager")
    offer = market(session, league)
    row = next((r for r in offer if r["player_id"] == player_id), None)
    if row is None:
        raise ValueError("Ese jugador no está en el mercado de esta jornada")
    price = row["price"]
    if price > member.budget_remaining + 1e-6:
        raise ValueError("Presupuesto insuficiente")
    member.budget_remaining = round(member.budget_remaining - price, 1)
    is_starter = sum(1 for p in picks if p.starter) < league.lineup_size
    session.add(FantasyPick(member_id=member.id, player_id=player_id, buy_price=price,
                            buy_jornada=league.current_jornada, starter=is_starter))
    session.add(member)
    session.commit()
    return {"ok": True, "price": price, "budget_remaining": member.budget_remaining}


def sell(session: Session, league: FantasyLeague, member: FantasyMember, player_id: int) -> dict:
    pick = session.exec(
        select(FantasyPick).where(FantasyPick.member_id == member.id,
                                  FantasyPick.player_id == player_id)
    ).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    price = price_map(session, league).get(player_id, pick.buy_price)
    member.budget_remaining = round(member.budget_remaining + price, 1)
    session.delete(pick)
    session.add(member)
    session.commit()
    return {"ok": True, "price": price, "budget_remaining": member.budget_remaining}


def set_lineup(session: Session, league: FantasyLeague, member: FantasyMember, starter_ids: list[int]) -> dict:
    if len(starter_ids) > league.lineup_size:
        raise ValueError(f"Solo puedes alinear {league.lineup_size} titulares")
    picks = picks_of(session, member.id)
    owned = {p.player_id for p in picks}
    if not set(starter_ids).issubset(owned):
        raise ValueError("Algún titular no está en tu plantilla")
    for p in picks:
        p.starter = p.player_id in starter_ids
        session.add(p)
    session.commit()
    return {"ok": True, "starters": starter_ids}


def advance(session: Session, league: FantasyLeague) -> dict:
    """Puntúa la siguiente jornada para todos los participantes y avanza la liga."""
    if league.current_jornada >= league.max_jornada:
        return {"ok": False, "done": True, "message": "La temporada ya está completa"}
    nxt = league.current_jornada + 1
    pts = jornada_points(session, league, nxt)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    breakdown = []
    for m in members:
        starters = [p for p in picks_of(session, m.id) if p.starter]
        gained = round(sum(pts.get(p.player_id, 0.0) for p in starters), 1)
        m.total_points = round(m.total_points + gained, 1)
        session.add(m)
        breakdown.append({"member_id": m.id, "manager": m.manager_name, "gained": gained})
    league.current_jornada = nxt
    session.add(league)
    session.commit()
    return {"ok": True, "jornada": nxt, "breakdown": breakdown,
            "done": league.current_jornada >= league.max_jornada}


def standings(session: Session, league: FantasyLeague) -> list[dict]:
    prices = price_map(session, league)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    rows = []
    for m in members:
        picks = picks_of(session, m.id)
        squad_value = round(sum(prices.get(p.player_id, 0.0) for p in picks), 1)
        rows.append({
            "member_id": m.id, "user_id": m.user_id, "manager": m.manager_name,
            "total_points": m.total_points, "budget_remaining": m.budget_remaining,
            "squad_value": squad_value, "worth": round(squad_value + m.budget_remaining, 1),
            "squad_count": len(picks),
        })
    rows.sort(key=lambda r: r["total_points"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def league_out(league: FantasyLeague) -> dict:
    return {
        "id": league.id, "name": league.name, "join_code": league.join_code,
        "owner_user_id": league.owner_user_id, "competition": league.competition,
        "grupo": league.grupo, "season": league.season, "budget": league.budget,
        "squad_size": league.squad_size, "lineup_size": league.lineup_size,
        "win_bonus": league.win_bonus, "start_jornada": league.start_jornada,
        "current_jornada": league.current_jornada, "max_jornada": league.max_jornada,
    }


def my_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> list[dict]:
    prices = price_map(session, league)
    conf = conference_games(session, league.competition, league.grupo, league.season)
    out = []
    for p in picks_of(session, member.id):
        d = conf.get(p.player_id, {})
        cur = prices.get(p.player_id, p.buy_price)
        out.append({
            "player_id": p.player_id, "name": d.get("name", "?"), "feb_code": d.get("feb_code"),
            "team": d.get("team"), "buy_price": p.buy_price, "price": cur,
            "delta": round(cur - p.buy_price, 1), "starter": p.starter,
        })
    out.sort(key=lambda r: (not r["starter"], -r["price"]))
    return out
