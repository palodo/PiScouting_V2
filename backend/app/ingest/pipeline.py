"""Pipeline de ingesta: vuelca un partido de LiveStats en la base de datos.

`ingest_match` es autosuficiente: crea los equipos y jugadores que necesite a
partir de la cabecera del partido, de modo que se puede ingerir un partido suelto
sin haber corrido antes el rastreo completo de clasificación/calendario.
"""
from __future__ import annotations

import json
from datetime import datetime, date
from typing import Optional

from sqlmodel import Session, select

from ..models import Team, Player, Match, PlayerMatchStat, Shot
from .feb_client import FEBClient
from .match_parser import parse_match


def _parse_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    m = None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.split(" ")[0].strip(), fmt).date()
        except ValueError:
            continue
    return m


def upsert_team(session: Session, *, feb_code: str, name: str, logo: Optional[str],
                competition: str, grupo: Optional[str], season: str,
                feb_url: Optional[str] = None) -> Team:
    feb_url = feb_url or f"/Equipo.aspx?i={feb_code}"
    team = session.exec(select(Team).where(Team.feb_code == feb_code, Team.season == season)).first()
    if team is None:
        team = session.exec(select(Team).where(Team.feb_url == feb_url)).first()
    if team is None:
        team = Team(feb_url=feb_url, feb_code=feb_code, name=name, logo=logo,
                    competition=competition, grupo=grupo, season=season)
        session.add(team)
        session.flush()
    else:
        team.name = name or team.name
        team.logo = logo or team.logo
        if grupo:
            team.grupo = grupo
        team.updated_at = datetime.utcnow()
    return team


def upsert_player(session: Session, *, feb_code: str, name: str, photo: Optional[str]) -> Player:
    player = session.exec(select(Player).where(Player.feb_code == feb_code)).first()
    if player is None:
        player = Player(feb_code=feb_code, name=name or feb_code, photo_url=photo)
        session.add(player)
        session.flush()
    else:
        if name:
            player.name = name
        if photo:
            player.photo_url = photo
    return player


def ingest_match(session: Session, client: FEBClient, partido_id: str, *,
                 competition: str, season: str, grupo: Optional[str] = None,
                 jornada: Optional[str] = None, jornada_num: Optional[int] = None,
                 home_feb_code: Optional[str] = None,
                 away_feb_code: Optional[str] = None,
                 match_date: Optional[date] = None) -> Match:
    data = parse_match(client.get_match_data(partido_id))
    header = data["header"]
    teams = header["teams"]
    if len(teams) < 2:
        raise RuntimeError(f"Partido {partido_id}: cabecera sin 2 equipos")

    # Determinar qué índice (0/1) es local. Si el calendario nos dio los códigos,
    # mapeamos por código; si no, asumimos orden [local, visitante].
    idx_by_code = {t["id"]: i for i, t in enumerate(teams) if t.get("id")}
    if home_feb_code and away_feb_code and home_feb_code in idx_by_code and away_feb_code in idx_by_code:
        home_index = idx_by_code[home_feb_code]
    else:
        home_index = 0
    away_index = 1 - home_index

    def team_row(idx: int) -> Team:
        t = teams[idx]
        return upsert_team(
            session, feb_code=t["id"], name=t["name"], logo=t["logo"],
            competition=competition, grupo=grupo, season=season,
        )

    home_team = team_row(home_index)
    away_team = team_row(away_index)

    # Match (upsert por partido_id)
    match = session.exec(select(Match).where(Match.partido_id == partido_id)).first()
    if match is None:
        match = Match(partido_id=partido_id, season=season, competition=competition)
        session.add(match)
    match.competition = competition
    match.grupo = grupo or match.grupo
    match.jornada = jornada or match.jornada
    match.jornada_num = jornada_num if jornada_num is not None else match.jornada_num
    match.match_date = match_date or _parse_date(header.get("starttime")) or match.match_date
    match.home_team_id = home_team.id
    match.away_team_id = away_team.id
    match.home_score = teams[home_index]["pts"]
    match.away_score = teams[away_index]["pts"]
    match.venue = header.get("venue")
    match.referees = header.get("referees")
    # Reordenar parciales a home/away según índice local
    quarters = header.get("quarters") or []
    if home_index == 1:
        quarters = [{"n": q["n"], "home": q["away"], "away": q["home"]} for q in quarters]
    match.quarter_scores = json.dumps(quarters, ensure_ascii=False)
    match.status = "ingested"
    match.ingested_at = datetime.utcnow()
    session.flush()

    # Limpiar detalle previo para reingestas idempotentes
    for old in session.exec(select(PlayerMatchStat).where(PlayerMatchStat.match_id == match.id)):
        session.delete(old)
    for old in session.exec(select(Shot).where(Shot.match_id == match.id)):
        session.delete(old)
    session.flush()

    team_by_index = {home_index: home_team, away_index: away_team}

    # Boxscore -> PlayerMatchStat  (+ mapa (team_index,dorsal)->player para tiros)
    dorsal_to_player: dict[tuple[int, str], Player] = {}
    for p in data["players"]:
        ti = p["team_index"]
        team = team_by_index.get(ti)
        if team is None:
            continue
        player = upsert_player(session, feb_code=p["player_code"], name=p["name"], photo=p["photo"])
        if p.get("dorsal"):
            dorsal_to_player[(ti, p["dorsal"])] = player
        session.add(PlayerMatchStat(
            match_id=match.id, team_id=team.id, player_id=player.id,
            is_home=(ti == home_index), dorsal=p["dorsal"], starter=p["starter"],
            seconds=p["seconds"], pts=p["pts"],
            t2m=p["t2m"], t2a=p["t2a"], t3m=p["t3m"], t3a=p["t3a"],
            tlm=p["tlm"], tla=p["tla"], oreb=p["oreb"], dreb=p["dreb"], treb=p["treb"],
            ast=p["ast"], stl=p["stl"], tov=p["tov"], blk_for=p["blk_for"],
            blk_against=p["blk_against"], pf_committed=p["pf_committed"],
            pf_received=p["pf_received"], dunks=p["dunks"], val=p["val"],
            plus_minus=p["plus_minus"],
        ))

    # Shotchart -> Shot
    for s in data["shots"]:
        ti = s["team_index"]
        team = team_by_index.get(ti)
        if team is None:
            continue
        player = dorsal_to_player.get((ti, s.get("dorsal"))) if s.get("dorsal") else None
        session.add(Shot(
            match_id=match.id, team_id=team.id,
            player_id=player.id if player else None,
            is_home=(ti == home_index), x=s["x"], y=s["y"], made=s["made"],
            quarter=s["quarter"], clock=s["clock"], seconds_elapsed=s["seconds_elapsed"],
        ))

    session.commit()
    return match
