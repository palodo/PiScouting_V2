"""Agregados analíticos calculados sobre los partidos almacenados.

Todo se deriva de la tabla partido-a-partido, por eso podemos ofrecer métricas que
las estadísticas acumuladas de la FEB no dan: +/- por jugador y equipo, splits
local/visitante, forma reciente, eficiencias, etc.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from .models import Team, Player, Match, PlayerMatchStat, Shot


def _pct(made: int, att: int) -> float:
    return round(100.0 * made / att, 1) if att else 0.0


def _safe_div(a: float, b: float) -> float:
    return round(a / b, 1) if b else 0.0


def team_record(session: Session, team_id: int, up_to_jornada: Optional[int] = None) -> dict:
    q = select(Match).where(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        Match.status.in_(("played", "ingested")),
    )
    if up_to_jornada is not None:
        q = q.where(Match.jornada_num <= up_to_jornada)
    matches = session.exec(q).all()
    wins = losses = pf = pa = 0
    form: list[dict] = []
    for m in matches:
        is_home = m.home_team_id == team_id
        my = m.home_score if is_home else m.away_score
        opp = m.away_score if is_home else m.home_score
        if my is None or opp is None:
            continue
        pf += my
        pa += opp
        won = my > opp
        wins += int(won)
        losses += int(not won)
        form.append({
            "match_id": m.id, "date": m.match_date.isoformat() if m.match_date else None,
            "opponent_id": m.away_team_id if is_home else m.home_team_id,
            "is_home": is_home, "pts_for": my, "pts_against": opp, "won": won,
        })
    games = wins + losses
    form.sort(key=lambda x: (x["date"] or ""))
    return {
        "games": games, "wins": wins, "losses": losses,
        "win_pct": _pct(wins, games),
        "pts_for_avg": _safe_div(pf, games), "pts_against_avg": _safe_div(pa, games),
        "diff_avg": _safe_div(pf - pa, games),
        "form": form,
    }


def team_shooting(session: Session, team_id: int) -> dict:
    stats = session.exec(select(PlayerMatchStat).where(PlayerMatchStat.team_id == team_id)).all()
    agg = {k: 0 for k in ("t2m", "t2a", "t3m", "t3a", "tlm", "tla", "oreb", "dreb",
                          "treb", "ast", "stl", "tov", "pts")}
    for s in stats:
        for k in agg:
            agg[k] += getattr(s, k)
    return {
        "fg2_pct": _pct(agg["t2m"], agg["t2a"]),
        "fg3_pct": _pct(agg["t3m"], agg["t3a"]),
        "ft_pct": _pct(agg["tlm"], agg["tla"]),
        "reb_off": agg["oreb"], "reb_def": agg["dreb"], "reb_total": agg["treb"],
        "assists": agg["ast"], "steals": agg["stl"], "turnovers": agg["tov"],
        "totals": agg,
    }


def team_roster(session: Session, team_id: int) -> list[dict]:
    rows = session.exec(
        select(PlayerMatchStat, Player)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .where(PlayerMatchStat.team_id == team_id)
    ).all()
    by_player: dict[int, dict] = {}
    for st, pl in rows:
        d = by_player.setdefault(pl.id, {
            "player_id": pl.id, "name": pl.name, "feb_code": pl.feb_code,
            "photo_url": pl.photo_url, "games": 0,
            "_pts": 0, "_val": 0, "_pm": 0, "_sec": 0, "_treb": 0, "_ast": 0,
            "t2m": 0, "t2a": 0, "t3m": 0, "t3a": 0, "tlm": 0, "tla": 0,
        })
        d["games"] += 1
        d["_pts"] += st.pts
        d["_val"] += st.val
        d["_pm"] += st.plus_minus
        d["_sec"] += st.seconds
        d["_treb"] += st.treb
        d["_ast"] += st.ast
        for k in ("t2m", "t2a", "t3m", "t3a", "tlm", "tla"):
            d[k] += getattr(st, k)
    out = []
    for d in by_player.values():
        g = d["games"] or 1
        fga = d["t2a"] + d["t3a"]
        ts_den = 2 * (fga + 0.44 * d["tla"])
        out.append({
            "player_id": d["player_id"], "name": d["name"], "feb_code": d["feb_code"],
            "photo_url": d["photo_url"], "games": d["games"],
            "ppg": round(d["_pts"] / g, 1), "val_avg": round(d["_val"] / g, 1),
            "plus_minus_avg": round(d["_pm"] / g, 1),
            "min_avg": round(d["_sec"] / g / 60, 1),
            "rpg": round(d["_treb"] / g, 1), "apg": round(d["_ast"] / g, 1),
            "fg2_pct": _pct(d["t2m"], d["t2a"]), "fg3_pct": _pct(d["t3m"], d["t3a"]),
            "ft_pct": _pct(d["tlm"], d["tla"]),
            "ts_pct": round(d["_pts"] / ts_den * 100, 1) if ts_den else 0.0,
            "fg3a_avg": round(d["t3a"] / g, 1),
        })
    out.sort(key=lambda x: x["ppg"], reverse=True)
    return out


def player_summary(session: Session, player_id: int) -> dict:
    rows = session.exec(
        select(PlayerMatchStat, Match)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .where(PlayerMatchStat.player_id == player_id)
    ).all()
    player = session.get(Player, player_id)
    agg = {k: 0 for k in ("pts", "val", "plus_minus", "seconds", "treb", "oreb", "dreb",
                          "ast", "stl", "tov", "blk_for", "pf_committed",
                          "t2m", "t2a", "t3m", "t3a", "tlm", "tla")}
    gamelog = []
    for st, m in rows:
        for k in agg:
            agg[k] += getattr(st, k)
        gamelog.append({
            "match_id": m.id, "date": m.match_date.isoformat() if m.match_date else None,
            "jornada": m.jornada, "pts": st.pts, "val": st.val,
            "plus_minus": st.plus_minus, "min": round(st.seconds / 60, 1),
            "treb": st.treb, "ast": st.ast,
            "t2": f"{st.t2m}/{st.t2a}", "t3": f"{st.t3m}/{st.t3a}", "tl": f"{st.tlm}/{st.tla}",
        })
    g = len(rows) or 1
    gamelog.sort(key=lambda x: (x["date"] or ""))
    return {
        "player_id": player_id,
        "name": player.name if player else None,
        "feb_code": player.feb_code if player else None,
        "photo_url": player.photo_url if player else None,
        "games": len(rows),
        "averages": {
            "ppg": round(agg["pts"] / g, 1), "val_avg": round(agg["val"] / g, 1),
            "plus_minus_avg": round(agg["plus_minus"] / g, 1),
            "min_avg": round(agg["seconds"] / g / 60, 1),
            "rpg": round(agg["treb"] / g, 1), "apg": round(agg["ast"] / g, 1),
            "spg": round(agg["stl"] / g, 1), "topg": round(agg["tov"] / g, 1),
            "fg2_pct": _pct(agg["t2m"], agg["t2a"]),
            "fg3_pct": _pct(agg["t3m"], agg["t3a"]),
            "ft_pct": _pct(agg["tlm"], agg["tla"]),
        },
        "totals": agg,
        "gamelog": gamelog,
    }


def team_rankings(session: Session, competition: str, grupo: Optional[str], season: str) -> list[dict]:
    q = select(Team).where(Team.competition == competition, Team.season == season)
    if grupo:
        q = q.where(Team.grupo == grupo)
    teams = session.exec(q).all()
    table = []
    for t in teams:
        rec = team_record(session, t.id)
        if rec["games"] == 0:
            continue
        table.append({
            "team_id": t.id, "name": t.name, "logo": t.logo, "grupo": t.grupo,
            **{k: rec[k] for k in ("games", "wins", "losses", "win_pct",
                                   "pts_for_avg", "pts_against_avg", "diff_avg")},
        })
    table.sort(key=lambda x: (x["wins"], x["diff_avg"]), reverse=True)
    for i, row in enumerate(table, 1):
        row["rank"] = i
    return table


def player_leaders(session: Session, competition: str, season: str,
                   stat: str = "pts", limit: int = 25) -> list[dict]:
    rows = session.exec(
        select(PlayerMatchStat, Player, Team)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(Team.competition == competition, Team.season == season)
    ).all()
    valid = {"pts", "val", "plus_minus", "treb", "ast", "stl"}
    key = stat if stat in valid else "pts"
    by_player: dict[int, dict] = {}
    for st, pl, tm in rows:
        d = by_player.setdefault(pl.id, {
            "player_id": pl.id, "name": pl.name, "photo_url": pl.photo_url,
            "team_id": tm.id, "team": tm.name, "games": 0, "_sum": 0,
        })
        d["games"] += 1
        d["_sum"] += getattr(st, key)
    leaders = []
    for d in by_player.values():
        if d["games"] < 1:
            continue
        leaders.append({
            "player_id": d["player_id"], "name": d["name"], "photo_url": d["photo_url"],
            "team_id": d["team_id"], "team": d["team"], "games": d["games"],
            "stat": key, "avg": round(d["_sum"] / d["games"], 1), "total": d["_sum"],
        })
    leaders.sort(key=lambda x: x["avg"], reverse=True)
    return leaders[:limit]
