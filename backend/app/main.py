"""API FastAPI de PiScouting."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select, func

from .db import engine, init_db, get_session
from .config import DEFAULT_SEASON
from .models import Team, Player, Match, PlayerMatchStat, User
from . import analytics, shots as shots_mod, scouting as scouting_mod, auth
from .ingest.crawl import ingest_team

app = FastAPI(title="PiScouting API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    counts = {}
    for model, label in [(Team, "teams"), (Player, "players"), (Match, "matches"),
                         (PlayerMatchStat, "player_stats")]:
        counts[label] = session.exec(select(func.count()).select_from(model)).one()
    return {"status": "ok", "counts": counts}


@app.get("/api/meta/competitions")
def competitions(season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    teams = session.exec(select(Team).where(Team.season == season)).all()
    out: dict[str, dict] = {}
    for t in teams:
        c = out.setdefault(t.competition, {"competition": t.competition, "grupos": set(), "teams": 0})
        c["teams"] += 1
        if t.grupo:
            c["grupos"].add(t.grupo)
    result = []
    for c in out.values():
        result.append({"competition": c["competition"], "teams": c["teams"],
                       "grupos": sorted(c["grupos"])})
    result.sort(key=lambda x: x["competition"])
    return {"season": season, "competitions": result}


@app.get("/api/teams")
def list_teams(competition: Optional[str] = None, grupo: Optional[str] = None,
               season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    q = select(Team).where(Team.season == season)
    if competition:
        q = q.where(Team.competition == competition)
    if grupo:
        q = q.where(Team.grupo == grupo)
    teams = session.exec(q.order_by(Team.name)).all()
    return [{"team_id": t.id, "name": t.name, "logo": t.logo,
             "competition": t.competition, "grupo": t.grupo} for t in teams]


@app.get("/api/teams/{team_id}")
def team_detail(team_id: int, session: Session = Depends(get_session)):
    t = session.get(Team, team_id)
    if not t:
        raise HTTPException(404, "Equipo no encontrado")
    return {
        "team_id": t.id, "name": t.name, "logo": t.logo,
        "competition": t.competition, "grupo": t.grupo, "season": t.season,
        "record": analytics.team_record(session, team_id),
        "shooting": analytics.team_shooting(session, team_id),
        "roster": analytics.team_roster(session, team_id),
    }


@app.get("/api/players/{player_id}")
def player_detail(player_id: int, session: Session = Depends(get_session)):
    if not session.get(Player, player_id):
        raise HTTPException(404, "Jugador no encontrado")
    return analytics.player_summary(session, player_id)


@app.get("/api/matches/{match_id}")
def match_detail(match_id: int, session: Session = Depends(get_session)):
    m = session.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Partido no encontrado")
    home = session.get(Team, m.home_team_id)
    away = session.get(Team, m.away_team_id)

    def boxscore(team_id: int):
        rows = session.exec(
            select(PlayerMatchStat, Player)
            .join(Player, Player.id == PlayerMatchStat.player_id)
            .where(PlayerMatchStat.match_id == match_id, PlayerMatchStat.team_id == team_id)
            .order_by(PlayerMatchStat.pts.desc())
        ).all()
        return [{
            "player_id": pl.id, "name": pl.name, "dorsal": st.dorsal,
            "starter": st.starter, "min": round(st.seconds / 60, 1),
            "pts": st.pts, "val": st.val, "plus_minus": st.plus_minus,
            "t2": f"{st.t2m}/{st.t2a}", "t3": f"{st.t3m}/{st.t3a}", "tl": f"{st.tlm}/{st.tla}",
            "treb": st.treb, "oreb": st.oreb, "dreb": st.dreb, "ast": st.ast,
            "stl": st.stl, "tov": st.tov, "blk": st.blk_for, "pf": st.pf_committed,
        } for st, pl in rows]

    return {
        "match_id": m.id, "partido_id": m.partido_id,
        "competition": m.competition, "grupo": m.grupo, "jornada": m.jornada,
        "date": m.match_date.isoformat() if m.match_date else None,
        "venue": m.venue, "referees": m.referees,
        "quarters": json.loads(m.quarter_scores) if m.quarter_scores else [],
        "home": {"team_id": home.id if home else None, "name": home.name if home else None,
                 "logo": home.logo if home else None, "score": m.home_score,
                 "boxscore": boxscore(m.home_team_id) if home else []},
        "away": {"team_id": away.id if away else None, "name": away.name if away else None,
                 "logo": away.logo if away else None, "score": m.away_score,
                 "boxscore": boxscore(m.away_team_id) if away else []},
    }


@app.get("/api/rankings/teams")
def rankings_teams(competition: str, grupo: Optional[str] = None,
                   season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    return analytics.team_rankings(session, competition, grupo, season)


@app.get("/api/rankings/players")
def rankings_players(competition: str, stat: str = "pts", limit: int = 25,
                     season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    return analytics.player_leaders(session, competition, season, stat=stat, limit=limit)


@app.get("/api/compare/teams")
def compare_teams(ids: str, session: Session = Depends(get_session)):
    team_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    out = []
    for tid in team_ids:
        t = session.get(Team, tid)
        if not t:
            continue
        out.append({
            "team_id": t.id, "name": t.name, "logo": t.logo,
            "record": analytics.team_record(session, tid),
            "shooting": analytics.team_shooting(session, tid),
        })
    return out


@app.get("/api/shots/team/{team_id}")
def shots_team(team_id: int, session: Session = Depends(get_session)):
    data = shots_mod.shots_for_team(session, team_id)
    return {"summary": shots_mod.shot_zone_summary(data), "shots": data}


@app.get("/api/shots/player/{player_id}")
def shots_player(player_id: int, session: Session = Depends(get_session)):
    data = shots_mod.shots_for_player(session, player_id)
    return {"summary": shots_mod.shot_zone_summary(data), "shots": data}


@app.get("/api/shots/match/{match_id}")
def shots_match(match_id: int, team_id: Optional[int] = None,
                session: Session = Depends(get_session)):
    data = shots_mod.shots_for_match(session, match_id, team_id)
    return {"summary": shots_mod.shot_zone_summary(data), "shots": data}


# ============================ Autenticación ============================
class SignupBody(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    team_id: Optional[int] = None


class LoginBody(BaseModel):
    email: str
    password: str


class TeamBody(BaseModel):
    team_id: int


def _user_out(session: Session, user: User) -> dict:
    team = session.get(Team, user.team_id) if user.team_id else None
    return {
        "id": user.id, "email": user.email, "name": user.name,
        "team": {"team_id": team.id, "name": team.name, "logo": team.logo,
                 "competition": team.competition, "grupo": team.grupo} if team else None,
    }


@app.post("/api/auth/signup")
def signup(body: SignupBody, session: Session = Depends(get_session)):
    email = body.email.strip().lower()
    if not email or not body.password:
        raise HTTPException(400, "Email y contraseña obligatorios")
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(409, "Ese email ya está registrado")
    user = User(email=email, password_hash=auth.hash_password(body.password),
                name=body.name, team_id=body.team_id)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"token": auth.create_token(user.id), "user": _user_out(session, user)}


@app.post("/api/auth/login")
def login(body: LoginBody, session: Session = Depends(get_session)):
    email = body.email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Credenciales incorrectas")
    return {"token": auth.create_token(user.id), "user": _user_out(session, user)}


@app.get("/api/auth/me")
def me(user: User = Depends(auth.get_current_user), session: Session = Depends(get_session)):
    return _user_out(session, user)


@app.put("/api/auth/me/team")
def set_team(body: TeamBody, user: User = Depends(auth.get_current_user),
             session: Session = Depends(get_session)):
    if not session.get(Team, body.team_id):
        raise HTTPException(404, "Equipo no encontrado")
    user.team_id = body.team_id
    session.add(user)
    session.commit()
    return _user_out(session, user)


# ============================ Scouting ============================
@app.get("/api/teams/{team_id}/schedule")
def team_schedule(team_id: int, session: Session = Depends(get_session)):
    return scouting_mod.schedule(session, team_id)


@app.get("/api/teams/{team_id}/next")
def team_next(team_id: int, session: Session = Depends(get_session)):
    return scouting_mod.next_opponent(session, team_id)


@app.get("/api/me/dashboard")
def my_dashboard(sim_jornada: Optional[int] = None,
                 user: User = Depends(auth.get_current_user),
                 session: Session = Depends(get_session)):
    if not user.team_id:
        raise HTTPException(400, "Todavía no has elegido equipo")
    return scouting_mod.dashboard(session, user.team_id, sim_jornada=sim_jornada)


@app.get("/api/scout/{team_id}")
def scout(team_id: int, session: Session = Depends(get_session)):
    report = scouting_mod.report(session, team_id)
    if not report:
        raise HTTPException(404, "Equipo no encontrado")
    return report


@app.post("/api/scout/{team_id}/prepare")
def scout_prepare(team_id: int, limit: int = 20, session: Session = Depends(get_session)):
    """Ingiere bajo demanda el detalle de los partidos del equipo (bounded)."""
    if not session.get(Team, team_id):
        raise HTTPException(404, "Equipo no encontrado")
    return ingest_team(session, team_id, limit=limit)


@app.get("/api/scout/{team_id}/pdf")
def scout_pdf(team_id: int, session: Session = Depends(get_session)):
    """Genera y descarga el informe de scouting en PDF."""
    from . import pdf_report
    team = session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Equipo no encontrado")
    pdf = pdf_report.build_scouting_pdf(session, team_id)
    safe = "".join(c if c.isalnum() else "_" for c in team.name)[:40]
    return StreamingResponse(
        pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="scouting_{safe}.pdf"'},
    )
