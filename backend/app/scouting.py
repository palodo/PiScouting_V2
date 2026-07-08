"""Scouting: calendario, próximo rival, métricas avanzadas e informe completo.

Combina datos de calendario (disponibles para todos los equipos al instante) con el
detalle partido-a-partido (boxscore + tiros) que se ingiere bajo demanda por equipo.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlmodel import Session, select

from .models import Team, Match, PlayerMatchStat
from . import analytics


def _opponent(session: Session, m: Match, team_id: int) -> dict:
    is_home = m.home_team_id == team_id
    opp_id = m.away_team_id if is_home else m.home_team_id
    opp = session.get(Team, opp_id) if opp_id else None
    my = m.home_score if is_home else m.away_score
    their = m.away_score if is_home else m.home_score
    won = (my is not None and their is not None and my > their)
    return {
        "match_id": m.id, "jornada": m.jornada, "jornada_num": m.jornada_num,
        "date": m.match_date.isoformat() if m.match_date else None,
        "is_home": is_home,
        "opponent_id": opp_id, "opponent": opp.name if opp else None,
        "opponent_logo": opp.logo if opp else None,
        "my_score": my, "their_score": their,
        "result": None if my is None else ("V" if won else "D"),
        "status": m.status,
    }


def schedule(session: Session, team_id: int) -> list[dict]:
    matches = session.exec(
        select(Match).where((Match.home_team_id == team_id) | (Match.away_team_id == team_id))
    ).all()
    rows = [_opponent(session, m, team_id) for m in matches]
    rows.sort(key=lambda r: (r["jornada_num"] if r["jornada_num"] is not None else 999,
                             r["date"] or ""))
    return rows


def next_opponent(session: Session, team_id: int, as_of: Optional[int] = None) -> Optional[dict]:
    """Próximo rival.

    - Con `as_of` (jornada simulada): primer partido con jornada > as_of. Sirve para
      revisar el análisis "a mitad de temporada" aunque los datos ya estén completos.
    - Sin `as_of`: primer partido sin resultado; si la temporada acabó, el siguiente por fecha.
    """
    sched = schedule(session, team_id)
    if as_of is not None:
        for r in sched:
            if r["jornada_num"] is not None and r["jornada_num"] > as_of:
                return r
        return None
    today = date.today().isoformat()
    for r in sched:
        if r["my_score"] is None:
            return r
    for r in sched:
        if r["date"] and r["date"] >= today:
            return r
    return None


def dashboard(session: Session, team_id: int, sim_jornada: Optional[int] = None) -> dict:
    """Panel de 'Mi equipo'. Con `sim_jornada` simula estar en esa jornada: el balance
    solo cuenta hasta ahí, los partidos posteriores se muestran como 'por jugar' y el
    próximo rival es el de la jornada siguiente."""
    team = session.get(Team, team_id)
    sched = schedule(session, team_id)
    jornadas = [r["jornada_num"] for r in sched if r["jornada_num"] is not None]
    total_jornadas = max(jornadas) if jornadas else 0

    if sim_jornada is not None:
        for r in sched:
            if r["jornada_num"] is not None and r["jornada_num"] > sim_jornada:
                # ocultar resultado de partidos "futuros"
                r["my_score"] = r["their_score"] = r["result"] = None
                r["status"] = "scheduled"
        record = analytics.team_record(session, team_id, up_to_jornada=sim_jornada)
        nxt = next_opponent(session, team_id, as_of=sim_jornada)
    else:
        record = analytics.team_record(session, team_id)
        nxt = next_opponent(session, team_id)

    return {
        "team": {"team_id": team.id, "name": team.name, "logo": team.logo,
                 "competition": team.competition, "grupo": team.grupo},
        "record": record,
        "next": nxt,
        "schedule": sched,
        "total_jornadas": total_jornadas,
        "sim_jornada": sim_jornada,
    }


def advanced(session: Session, team_id: int) -> dict:
    """Métricas avanzadas de equipo a partir del boxscore acumulado (partidos con detalle)."""
    stats = session.exec(select(PlayerMatchStat).where(PlayerMatchStat.team_id == team_id)).all()
    games = len({s.match_id for s in stats})
    agg = {k: 0 for k in ("pts", "t2a", "t2m", "t3a", "t3m", "tla", "tlm", "oreb",
                          "dreb", "treb", "ast", "tov", "stl")}
    for s in stats:
        for k in agg:
            agg[k] += getattr(s, k)
    fga = agg["t2a"] + agg["t3a"]
    fgm = agg["t2m"] + agg["t3m"]
    poss = fga + 0.44 * agg["tla"] - agg["oreb"] + agg["tov"]
    efg = (fgm + 0.5 * agg["t3m"]) / fga * 100 if fga else 0.0
    ts = agg["pts"] / (2 * (fga + 0.44 * agg["tla"])) * 100 if (fga + agg["tla"]) else 0.0
    return {
        "detail_games": games,
        "off_rtg": round(agg["pts"] / poss * 100, 1) if poss else 0.0,
        "pace": round(poss / games, 1) if games else 0.0,
        "efg_pct": round(efg, 1),
        "ts_pct": round(ts, 1),
        "ast_to": round(agg["ast"] / agg["tov"], 2) if agg["tov"] else 0.0,
        "oreb_avg": round(agg["oreb"] / games, 1) if games else 0.0,
        "three_rate": round(agg["t3a"] / fga * 100, 1) if fga else 0.0,  # % de tiros que son de 3
    }


def report(session: Session, team_id: int) -> dict:
    team = session.get(Team, team_id)
    if not team:
        return {}
    record = analytics.team_record(session, team_id)
    standings = analytics.team_rankings(session, team.competition, team.grupo, team.season)
    my_rank = next((r["rank"] for r in standings if r["team_id"] == team_id), None)
    roster = analytics.team_roster(session, team_id)
    sched = schedule(session, team_id)
    adv = advanced(session, team_id)

    # Jugadores clave: top por minutos entre los que tienen detalle
    key_players = sorted(roster, key=lambda p: p["min_avg"], reverse=True)[:5]
    shot_players = [p["player_id"] for p in sorted(roster, key=lambda p: p["ppg"], reverse=True)[:6]]

    return {
        "team": {
            "team_id": team.id, "name": team.name, "logo": team.logo,
            "competition": team.competition, "grupo": team.grupo, "season": team.season,
            "rank": my_rank, "total_teams": len(standings),
        },
        "record": record,
        "advanced": adv,
        "shooting": analytics.team_shooting(session, team_id),
        "standings": standings,
        "roster": roster,
        "key_players": key_players,
        "shot_player_ids": shot_players,
        "schedule": sched,
        "detail_ready": adv["detail_games"] > 0,
    }
