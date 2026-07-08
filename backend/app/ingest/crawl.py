"""Orquestador de ingesta: calendario -> equipos/partidos -> detalle (boxscore+tiros)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Callable

from sqlmodel import Session, select

from ..config import COMPETITIONS
from ..models import Team, Match
from .feb_client import FEBClient, team_code_from_url
from .calendar import crawl_calendar
from .pipeline import upsert_team, ingest_match, _parse_date


def _score(resultado: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not resultado or "-" not in resultado:
        return None, None
    try:
        h, a = resultado.split("-")
        return int(h), int(a)
    except ValueError:
        return None, None


def store_calendar(session: Session, competition: str, season: str, rows: list[dict]) -> list[Match]:
    """Crea/actualiza equipos y partidos (sin detalle) a partir del calendario."""
    matches: list[Match] = []
    for r in rows:
        home_code = team_code_from_url(r["local_url"])
        away_code = team_code_from_url(r["visitante_url"])
        if not (home_code and away_code):
            continue
        home = upsert_team(session, feb_code=home_code, name=r["local"], logo=None,
                           competition=competition, grupo=r["grupo"], season=season,
                           feb_url=r["local_url"])
        away = upsert_team(session, feb_code=away_code, name=r["visitante"], logo=None,
                           competition=competition, grupo=r["grupo"], season=season,
                           feb_url=r["visitante_url"])
        pid = r["partido_id"]
        match = session.exec(select(Match).where(Match.partido_id == pid)).first()
        if match is None:
            match = Match(partido_id=pid, season=season, competition=competition)
            session.add(match)
        match.grupo = r["grupo"]
        match.jornada = r["jornada"]
        match.jornada_num = r.get("jornada_num")
        match.match_date = _parse_date(r.get("fecha")) or match.match_date
        match.home_team_id = home.id
        match.away_team_id = away.id
        hs, as_ = _score(r.get("resultado"))
        if hs is not None:
            match.home_score, match.away_score = hs, as_
            if match.status == "scheduled":
                match.status = "played"
        matches.append(match)
    session.commit()
    return matches


def ingest_team(session: Session, team_id: int, *, limit: Optional[int] = None,
                client: Optional[FEBClient] = None,
                progress: Optional[Callable[[str], None]] = None) -> dict:
    """Ingiere el detalle (boxscore + tiros) de los partidos de un equipo aún sin detalle.

    Usado bajo demanda al abrir el scouting de un rival. Idempotente.
    """
    from ..models import Match
    team = session.get(Team, team_id)
    if not team:
        raise ValueError("Equipo no encontrado")
    client = client or FEBClient()
    log = progress or (lambda m: None)

    matches = session.exec(
        select(Match).where(
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
            Match.status == "played",  # jugados pero sin detalle
        )
    ).all()
    matches.sort(key=lambda m: (m.jornada_num or 0), reverse=True)  # los más recientes primero
    if limit:
        matches = matches[:limit]

    done = errors = 0
    for m in matches:
        home = session.get(Team, m.home_team_id)
        away = session.get(Team, m.away_team_id)
        try:
            ingest_match(
                session, client, m.partido_id,
                competition=team.competition, season=team.season, grupo=m.grupo,
                jornada=m.jornada, jornada_num=m.jornada_num,
                home_feb_code=home.feb_code if home else None,
                away_feb_code=away.feb_code if away else None,
                match_date=m.match_date,
            )
            done += 1
        except Exception as e:
            errors += 1
            log(f"error {m.partido_id}: {e}")
    return {"team_id": team_id, "ingested": done, "errors": errors, "remaining_before": len(matches)}


def crawl_and_store(session: Session, competition_key: str, season: str, *,
                    group_codes: Optional[list[int]] = None,
                    ingest_details: bool = True, limit: Optional[int] = None,
                    client: Optional[FEBClient] = None,
                    progress: Optional[Callable[[str], None]] = None) -> dict:
    """Rastrea una competición completa y opcionalmente ingiere el detalle de cada partido.

    Devuelve un resumen con conteos. `limit` acota el nº de partidos con detalle
    (útil para pruebas). Idempotente: reingerir actualiza en vez de duplicar.
    """
    if competition_key not in COMPETITIONS:
        raise ValueError(f"Competición no soportada: {competition_key}")
    slug = COMPETITIONS[competition_key]["calendar_slug"]
    codes = group_codes or [COMPETITIONS[competition_key]["calendar_code"]]
    client = client or FEBClient()
    log = progress or (lambda m: None)

    all_rows: list[dict] = []
    seen: set[str] = set()
    for code in codes:
        log(f"Rastreando calendario {competition_key} (code {code})...")
        try:
            rows = crawl_calendar(slug, season, code)
        except Exception as e:
            log(f"  error en calendario code {code}: {e}")
            continue
        for r in rows:
            if r["partido_id"] not in seen:
                seen.add(r["partido_id"])
                all_rows.append(r)
        log(f"  code {code}: {len(rows)} partidos")

    matches = store_calendar(session, competition_key, season, all_rows)
    played = [m for m in matches if m.status in ("played", "ingested")]
    log(f"{competition_key}: {len(matches)} partidos ({len(played)} jugados)")

    ingested = errors = 0
    if ingest_details:
        pending = [m for m in played if m.status != "ingested"]
        if limit:
            pending = pending[:limit]
        for i, m in enumerate(pending, 1):
            home = session.get(Team, m.home_team_id)
            away = session.get(Team, m.away_team_id)
            try:
                ingest_match(
                    session, client, m.partido_id,
                    competition=competition_key, season=season, grupo=m.grupo,
                    jornada=m.jornada, jornada_num=m.jornada_num,
                    home_feb_code=home.feb_code if home else None,
                    away_feb_code=away.feb_code if away else None,
                    match_date=m.match_date,
                )
                ingested += 1
                if i % 10 == 0 or i == len(pending):
                    log(f"  detalle {i}/{len(pending)} ingeridos...")
            except Exception as e:
                errors += 1
                log(f"  error partido {m.partido_id}: {e}")

    return {
        "competition": competition_key, "season": season,
        "matches": len(matches), "played": len(played),
        "ingested": ingested, "errors": errors,
        "finished_at": datetime.utcnow().isoformat(),
    }
