"""API FastAPI de PiScouting."""
from __future__ import annotations

import json
from typing import Optional

import threading

from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select, func

from .db import engine, init_db, get_session
from .config import DEFAULT_SEASON
from .models import (Team, Player, Match, PlayerMatchStat, User, FantasyLeague,
                     PasswordReset, PushSubscription)
from . import analytics, shots as shots_mod, scouting as scouting_mod, auth, fantasy as fantasy_mod, cache, refresh as refresh_mod, mailer, push as push_mod
from .ingest.crawl import ingest_team

app = FastAPI(title="PiScouting API", version="0.1.0")

import os as _os
# Producción: define FRONTEND_ORIGIN con el dominio del frontend (coma-separado si son varios),
# p.ej. "https://piscouting.pages.dev". En dev se permite localhost/LAN por regex.
_frontend_origins = [o.strip() for o in _os.environ.get("FRONTEND_ORIGIN", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _warm_cache() -> None:
    """Precalienta la clasificación de cada grupo (lo más consultado) en segundo plano,
    para que el primer visitante ya la tenga instantánea aunque la caché esté vacía."""
    try:
        with Session(engine) as s:
            combos = set()
            for t in s.exec(select(Team.competition, Team.grupo, Team.season)).all():
                combos.add((t[0], t[1], t[2]))
            for competition, grupo, season in combos:
                try:
                    analytics.team_rankings(s, competition, grupo, season)
                except Exception:
                    pass
    except Exception:
        pass


@app.on_event("startup")
def _startup() -> None:
    init_db()
    import threading
    threading.Thread(target=_warm_cache, daemon=True).start()
    # empuja al móvil los avisos que se van creando (incluidos los del cron horario)
    push_mod.start_worker(engine)


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    counts = {}
    for model, label in [(Team, "teams"), (Player, "players"), (Match, "matches"),
                         (PlayerMatchStat, "player_stats")]:
        counts[label] = session.exec(select(func.count()).select_from(model)).one()
    # Cuándo se habló por última vez con la FEB. Va aquí, sin token, porque es la señal de
    # que la app sigue viva sola: si esta fecha se queda atrás, algo se ha roto.
    last = refresh_mod.last_result()
    return {
        "status": "ok", "counts": counts,
        "last_refresh": {
            "at": last.get("finished_at"), "ok": last.get("ok"),
            "pending_matches": last.get("pending_matches"),
            "match_errors": last.get("match_errors"),
            "running": refresh_mod.is_running(),
        } if last else None,
    }


# ===================== Actualización diaria (admin) =====================
def _check_admin(token: Optional[str]) -> None:
    admin_token = _os.environ.get("PISCOUTING_ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(503, "Actualización no configurada: define PISCOUTING_ADMIN_TOKEN")
    if not token or token != admin_token:
        raise HTTPException(403, "Token de administración inválido")


@app.post("/api/admin/refresh")
def admin_refresh(x_admin_token: Optional[str] = Header(default=None), wait: bool = False):
    """Actualiza la BBDD desde la FEB (calendarios + detalle nuevo + limpia caché).

    Es barata (~10 s) e idempotente: pensada para un cron cada hora, que es lo que hace que
    el fantasy puntúe la jornada solo en cuanto entra el último resultado.

    Protegido por la cabecera X-Admin-Token. Por defecto responde al momento y trabaja en
    segundo plano; con ?wait=true espera al resultado."""
    _check_admin(x_admin_token)
    if refresh_mod.is_running():
        return {"status": "already_running"}
    if wait:
        return refresh_mod.run_refresh()
    threading.Thread(target=refresh_mod.run_refresh, daemon=True).start()
    return {"status": "started"}


@app.get("/api/admin/refresh/status")
def admin_refresh_status(x_admin_token: Optional[str] = Header(default=None)):
    _check_admin(x_admin_token)
    return {"running": refresh_mod.is_running(), "last": refresh_mod.last_result()}


@cache.cached
def _competitions_data(session: Session, season: str) -> dict:
    teams = session.exec(select(Team).where(Team.season == season)).all()
    out: dict[str, dict] = {}
    for t in teams:
        c = out.setdefault(t.competition, {"competition": t.competition, "grupos": set(), "teams": 0})
        c["teams"] += 1
        if t.grupo:
            c["grupos"].add(t.grupo)
    result = [{"competition": c["competition"], "teams": c["teams"], "grupos": sorted(c["grupos"])}
              for c in out.values()]
    result.sort(key=lambda x: x["competition"])
    return {"season": season, "competitions": result}


@app.get("/api/meta/competitions")
def competitions(season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    return _competitions_data(session, season)


@cache.cached
def _teams_data(session: Session, competition: Optional[str], grupo: Optional[str], season: str) -> list:
    q = select(Team).where(Team.season == season)
    if competition:
        q = q.where(Team.competition == competition)
    if grupo:
        q = q.where(Team.grupo == grupo)
    teams = session.exec(q.order_by(Team.name)).all()
    return [{"team_id": t.id, "name": t.name, "logo": t.logo,
             "competition": t.competition, "grupo": t.grupo} for t in teams]


@app.get("/api/teams")
def list_teams(competition: Optional[str] = None, grupo: Optional[str] = None,
               season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    return _teams_data(session, competition, grupo, season)


@app.get("/api/jornada/list")
def jornada_list(competition: str, grupo: Optional[str] = None,
                 season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    return analytics.jornada_list(session, competition, grupo, season)


@app.get("/api/jornada/summary")
def jornada_summary(competition: str, jornada: int, grupo: Optional[str] = None,
                    season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    return analytics.jornada_summary(session, competition, grupo, season, jornada)


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
        "is_admin": auth.is_admin(user),
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


class GoogleBody(BaseModel):
    id_token: str


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str


def _make_reset(session: Session, user: User) -> str:
    """Crea un enlace de un solo uso e invalida los anteriores de ese usuario."""
    from datetime import datetime as _dt, timedelta as _td
    for old in session.exec(select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at == None)).all():  # noqa: E711
        old.used_at = _dt.utcnow()
        session.add(old)
    token, token_hash = auth.new_reset_token()
    session.add(PasswordReset(user_id=user.id, token_hash=token_hash,
                              expires_at=_dt.utcnow() + _td(minutes=auth.RESET_TTL_MIN)))
    session.commit()
    return f"{mailer.APP_URL}/?reset={token}"


@app.post("/api/auth/forgot")
def auth_forgot(body: ForgotBody, session: Session = Depends(get_session)):
    """Pide un enlace para cambiar la contraseña.

    Responde siempre lo mismo exista o no la cuenta: si dijera "ese email no está
    registrado" cualquiera podría averiguar quién tiene cuenta probando direcciones.
    """
    email = (body.email or "").strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    enviado = False
    if user:
        link = _make_reset(session, user)
        enviado = mailer.send_password_reset(user.email, link, auth.RESET_TTL_MIN)
    return {"ok": True, "sent": enviado, "mail_enabled": mailer.enabled()}


@app.post("/api/auth/reset")
def auth_reset(body: ResetBody, session: Session = Depends(get_session)):
    from datetime import datetime as _dt
    if len(body.password or "") < 6:
        raise HTTPException(400, "La contraseña debe tener al menos 6 caracteres")
    pr = session.exec(select(PasswordReset).where(
        PasswordReset.token_hash == auth.hash_reset_token(body.token))).first()
    if not pr or pr.used_at or pr.expires_at < _dt.utcnow():
        raise HTTPException(400, "Ese enlace ya no vale: pide uno nuevo")
    user = session.get(User, pr.user_id)
    if not user:
        raise HTTPException(400, "Ese enlace ya no vale: pide uno nuevo")
    user.password_hash = auth.hash_password(body.password)
    pr.used_at = _dt.utcnow()
    session.add_all([user, pr])
    session.commit()
    return {"ok": True, "token": auth.create_token(user.id)}


@app.post("/api/admin/reset-link")
def admin_reset_link(body: ForgotBody, user: User = Depends(auth.get_current_user),
                     session: Session = Depends(get_session)):
    """Genera el enlace a mano, para pasárselo a alguien por WhatsApp.

    Es la salida mientras no haya correo configurado, y el plan B si un correo no llega.
    """
    if not auth.is_admin(user):
        raise HTTPException(403, "Solo un administrador puede generar enlaces")
    email = (body.email or "").strip().lower()
    target = session.exec(select(User).where(User.email == email)).first()
    if not target:
        raise HTTPException(404, "No hay ninguna cuenta con ese email")
    return {"ok": True, "email": target.email, "link": _make_reset(session, target),
            "minutes": auth.RESET_TTL_MIN}


class PushSubBody(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: Optional[str] = None


class PushOffBody(BaseModel):
    endpoint: str


@app.get("/api/push/key")
def push_key():
    """Clave pública VAPID: el navegador la necesita para suscribirse."""
    return {"enabled": push_mod.enabled(), "key": push_mod.VAPID_PUBLIC_KEY or None}


@app.post("/api/push/subscribe")
def push_subscribe(body: PushSubBody, user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    if not push_mod.enabled():
        raise HTTPException(503, "Las notificaciones no están configuradas")
    sub = session.exec(select(PushSubscription).where(
        PushSubscription.endpoint == body.endpoint)).first()
    if sub:
        # el mismo dispositivo puede cambiar de dueño (móvil compartido, cierre de sesión)
        sub.user_id, sub.p256dh, sub.auth = user.id, body.p256dh, body.auth
        sub.failures = 0
    else:
        sub = PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.p256dh,
                               auth=body.auth, user_agent=(body.user_agent or "")[:200])
    session.add(sub)
    session.commit()
    return {"ok": True}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: PushOffBody, user: User = Depends(auth.get_current_user),
                     session: Session = Depends(get_session)):
    sub = session.exec(select(PushSubscription).where(
        PushSubscription.endpoint == body.endpoint,
        PushSubscription.user_id == user.id)).first()
    if sub:
        session.delete(sub)
        session.commit()
    return {"ok": True}


@app.post("/api/push/test")
def push_test(user: User = Depends(auth.get_current_user),
              session: Session = Depends(get_session)):
    """Se manda un aviso a uno mismo, para comprobar que el móvil lo recibe."""
    n = push_mod.send_to_user(session, user.id, "PiFantasy",
                              "Las notificaciones funcionan. Aquí te avisaremos de los "
                              "clausulazos y de tu jornada.")
    return {"ok": True, "sent": n}


@app.get("/api/auth/config")
def auth_config():
    """Qué formas de entrar están activas. El ID de cliente de Google es público (va en el
    propio botón), y viajar así evita tener que recompilar la web para cambiarlo."""
    from .config import GOOGLE_CLIENT_ID
    return {"google_client_id": GOOGLE_CLIENT_ID or None}


@app.post("/api/auth/google")
def google_login(body: GoogleBody, session: Session = Depends(get_session)):
    """Login/registro con Google. La web manda el id_token de Google Identity Services."""
    import secrets as _secrets
    from .config import GOOGLE_CLIENT_ID
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "El login con Google no está configurado")
    info = auth.verify_google_token(body.id_token)
    if not info:
        raise HTTPException(401, "No se pudo verificar la cuenta de Google")
    user = session.exec(select(User).where(User.email == info["email"])).first()
    if not user:
        user = User(email=info["email"], name=info.get("name"),
                    password_hash=auth.hash_password(_secrets.token_urlsafe(32)))
        session.add(user)
        session.commit()
        session.refresh(user)
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
    result = ingest_team(session, team_id, limit=limit)
    cache.clear()  # el detalle nuevo cambia los agregados: invalidar caché
    return result


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


# ============================ Fantasy ============================
from .models import FantasyMember  # noqa: E402


class CreateLeagueBody(BaseModel):
    name: str
    competition: str
    grupo: Optional[str] = None
    manager_name: str
    budget: float = 100.0
    squad_size: int = 10
    lineup_size: int = 5
    win_bonus: float = 4.0
    start_jornada: Optional[int] = None
    market_weekday: int = 4
    market_hour: int = 20
    market_duration_h: int = 24
    market_size: int = 10
    initial_squad: int = 5
    clause_factor: float = 2.0
    clause_lock_h: int = 24
    # calendario: día/hora del primer partido de cada jornada y corte del mercado.
    # `sim_mode` sin valor = lo decide la app según si la temporada está en marcha.
    sim_mode: Optional[bool] = None
    play_weekday: int = 5
    play_hour: int = 18
    play_duration_h: int = 30
    market_close_before_h: int = 24


class JoinLeagueBody(BaseModel):
    join_code: str
    manager_name: str


class BidBody(BaseModel):
    listing_id: int
    amount: float


class ListingBody(BaseModel):
    listing_id: int


class PlayerBody(BaseModel):
    player_id: int


class LineupBody(BaseModel):
    starter_ids: list[int]


def _get_league(session: Session, league_id: int) -> FantasyLeague:
    lg = session.get(FantasyLeague, league_id)
    if not lg:
        raise HTTPException(404, "Liga no encontrada")
    return lg


def _member_or_403(session: Session, league_id: int, user_id: int) -> FantasyMember:
    m = fantasy_mod.member_of(session, league_id, user_id)
    if not m:
        raise HTTPException(403, "No participas en esta liga")
    return m


@app.get("/api/fantasy/competitions")
def fantasy_competitions(season: str = DEFAULT_SEASON, session: Session = Depends(get_session)):
    from .config import FANTASY_COMPETITIONS
    teams = session.exec(select(Team).where(
        Team.season == season, Team.competition.in_(list(FANTASY_COMPETITIONS)))).all()
    out: dict[str, set] = {}
    for t in teams:
        out.setdefault(t.competition, set())
        if t.grupo:
            out[t.competition].add(t.grupo)
    result = [{"competition": c, "grupos": sorted(g)} for c, g in out.items()]
    result.sort(key=lambda x: x["competition"])
    return {"competitions": result}


@app.get("/api/fantasy/notifications")
def fantasy_notifications(limit: int = 40, user: User = Depends(auth.get_current_user),
                          session: Session = Depends(get_session)):
    """Campana: lo que te ha pasado a ti en todas tus ligas."""
    return fantasy_mod.notifications(session, user.id, min(max(limit, 1), 100))


@app.post("/api/fantasy/notifications/read")
def fantasy_notifications_read(user: User = Depends(auth.get_current_user),
                               session: Session = Depends(get_session)):
    return fantasy_mod.mark_notifications_read(session, user.id)


@app.get("/api/fantasy/leagues")
def fantasy_my_leagues(user: User = Depends(auth.get_current_user),
                       session: Session = Depends(get_session)):
    out = []
    for m in session.exec(select(FantasyMember).where(FantasyMember.user_id == user.id)).all():
        lg = session.get(FantasyLeague, m.league_id)
        if not lg:
            continue
        fantasy_mod.sync_market(session, lg)
        members = session.exec(select(FantasyMember).where(
            FantasyMember.league_id == lg.id)).all()
        out.append({**fantasy_mod.league_out(lg, fantasy_mod.league_state(session, lg)),
                    "member_points": m.total_points, "members": len(members)})
    return out


@app.post("/api/fantasy/leagues")
def fantasy_create(body: CreateLeagueBody, user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    fallback = user.name or user.email.split("@")[0]
    try:
        lg = fantasy_mod.create_league(
            session, user.id, body.name.strip() or "Mi liga", body.competition, body.grupo,
            DEFAULT_SEASON, body.manager_name.strip() or fallback,
            budget=body.budget, squad_size=body.squad_size, lineup_size=body.lineup_size,
            win_bonus=body.win_bonus, start_jornada=body.start_jornada,
            market_weekday=body.market_weekday, market_hour=body.market_hour,
            market_duration_h=body.market_duration_h, market_size=body.market_size,
            initial_squad=body.initial_squad, clause_factor=body.clause_factor,
            clause_lock_h=body.clause_lock_h, sim_mode=body.sim_mode,
            play_weekday=body.play_weekday, play_hour=body.play_hour,
            play_duration_h=body.play_duration_h,
            market_close_before_h=body.market_close_before_h)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return fantasy_mod.league_out(lg, fantasy_mod.league_state(session, lg))


@app.post("/api/fantasy/leagues/join")
def fantasy_join(body: JoinLeagueBody, user: User = Depends(auth.get_current_user),
                 session: Session = Depends(get_session)):
    lg = session.exec(select(FantasyLeague).where(
        FantasyLeague.join_code == body.join_code.strip().upper())).first()
    if not lg:
        raise HTTPException(404, "No existe una liga con ese código")
    fallback = user.name or user.email.split("@")[0]
    fantasy_mod.join_league(session, lg, user.id, body.manager_name.strip() or fallback)
    fantasy_mod.sync_market(session, lg)
    return fantasy_mod.league_out(lg, fantasy_mod.league_state(session, lg))


@app.get("/api/fantasy/leagues/{league_id}")
def fantasy_league_detail(league_id: int, user: User = Depends(auth.get_current_user),
                          session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    fantasy_mod.sync_market(session, lg)
    member = fantasy_mod.member_of(session, league_id, user.id)
    return {
        "league": fantasy_mod.league_out(lg, fantasy_mod.league_state(session, lg)),
        "is_owner": lg.owner_user_id == user.id,
        "standings": fantasy_mod.standings(session, lg),
        "my_member_id": member.id if member else None,
        "my_budget": member.budget_remaining if member else None,
        "my_committed": fantasy_mod.committed_amount(session, member.id) if member else 0.0,
        "my_squad": fantasy_mod.my_squad(session, lg, member) if member else [],
        "feed": fantasy_mod.feed(session, league_id, 30),
        "jornada_ranking": fantasy_mod.jornada_ranking(session, lg),
    }


@app.get("/api/fantasy/leagues/{league_id}/jornada/{jornada}")
def fantasy_jornada_ranking(league_id: int, jornada: int,
                            user: User = Depends(auth.get_current_user),
                            session: Session = Depends(get_session)):
    """Clasificación de una jornada concreta, para poder mirar atrás."""
    return fantasy_mod.jornada_ranking(session, _get_league(session, league_id), jornada)


@app.get("/api/fantasy/leagues/{league_id}/market")
def fantasy_market(league_id: int, user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    member = fantasy_mod.member_of(session, league_id, user.id)
    return fantasy_mod.market(session, lg, member)


@app.get("/api/fantasy/leagues/{league_id}/matches")
def fantasy_matches(league_id: int, jornada: Optional[int] = None,
                    user: User = Depends(auth.get_current_user),
                    session: Session = Depends(get_session)):
    """Partidos de una jornada con su estado (jugado, en juego, aplazado, adelantado).
    Sin `jornada`, la que está en curso o a punto de jugarse."""
    lg = _get_league(session, league_id)
    state = fantasy_mod.league_state(session, lg)
    j = jornada if jornada is not None else state["jornada"]
    return {
        "jornada": j,
        "phase": state["phase"],
        "kickoff_at": fantasy_mod._iso(state["kickoff_at"]),
        "ends_at": fantasy_mod._iso(state["ends_at"]),
        "matches": fantasy_mod.jornada_matches(session, lg, j),
    }


@app.get("/api/fantasy/leagues/{league_id}/clauses")
def fantasy_clauses(league_id: int, user: User = Depends(auth.get_current_user),
                    session: Session = Depends(get_session)):
    """Escaparate de cláusulas de toda la liga, para ir de clausulazo."""
    lg = _get_league(session, league_id)
    member = fantasy_mod.member_of(session, league_id, user.id)
    return {
        "players": fantasy_mod.league_clauses(session, lg, member),
        "my_budget": member.budget_remaining if member else 0.0,
        "committed": fantasy_mod.committed_amount(session, member.id) if member else 0.0,
        "clause_lock_h": lg.clause_lock_h,
    }


@app.post("/api/fantasy/leagues/{league_id}/bid")
def fantasy_bid(league_id: int, body: BidBody, user: User = Depends(auth.get_current_user),
                session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.place_bid(session, lg, m, body.listing_id, body.amount)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/bid/cancel")
def fantasy_bid_cancel(league_id: int, body: ListingBody,
                       user: User = Depends(auth.get_current_user),
                       session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.cancel_bid(session, lg, m, body.listing_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/market/close")
def fantasy_market_close(league_id: int, user: User = Depends(auth.get_current_user),
                         session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    if lg.owner_user_id != user.id and not auth.is_admin(user):
        raise HTTPException(403, "Solo el creador puede cerrar el mercado")
    try:
        return fantasy_mod.close_market_now(session, lg)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/market/open")
def fantasy_market_open(league_id: int, user: User = Depends(auth.get_current_user),
                        session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    if lg.owner_user_id != user.id and not auth.is_admin(user):
        raise HTTPException(403, "Solo el creador puede abrir el mercado")
    try:
        return fantasy_mod.open_market_now(session, lg)
    except ValueError as e:
        raise HTTPException(400, str(e))


class OfferBody(BaseModel):
    player_id: int
    amount: float


@app.get("/api/fantasy/leagues/{league_id}/players")
def fantasy_players(league_id: int, user: User = Depends(auth.get_current_user),
                    session: Session = Depends(get_session)):
    """Todos los jugadores de la conferencia, con dueño y cláusula. Para buscar y
    comparar; el orden y los filtros los hace la web."""
    lg = _get_league(session, league_id)
    member = fantasy_mod.member_of(session, league_id, user.id)
    return {"players": fantasy_mod.league_players(session, lg, member),
            "my_member_id": member.id if member else None}


@app.get("/api/fantasy/leagues/{league_id}/offers")
def fantasy_offers(league_id: int, user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    member = fantasy_mod.member_of(session, league_id, user.id)
    return fantasy_mod.offers_for(session, lg, member)


@app.post("/api/fantasy/leagues/{league_id}/offers")
def fantasy_offer_make(league_id: int, body: OfferBody,
                       user: User = Depends(auth.get_current_user),
                       session: Session = Depends(get_session)):
    """Oferta por el jugador de otro mánager."""
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.make_offer(session, lg, m, body.player_id, body.amount)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/offers/{offer_id}/{decision}")
def fantasy_offer_resolve(league_id: int, offer_id: int, decision: str,
                          user: User = Depends(auth.get_current_user),
                          session: Session = Depends(get_session)):
    if decision not in ("accept", "reject"):
        raise HTTPException(400, "Decisión no válida")
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.resolve_offer(session, lg, m, offer_id, decision == "accept")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/sell/cancel")
def fantasy_sell_cancel(league_id: int, body: PlayerBody,
                        user: User = Depends(auth.get_current_user),
                        session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.cancel_sale(session, lg, m, body.player_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/sell")
def fantasy_sell(league_id: int, body: PlayerBody, user: User = Depends(auth.get_current_user),
                 session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.put_on_sale(session, lg, m, body.player_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/lineup")
def fantasy_lineup(league_id: int, body: LineupBody, user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.set_lineup(session, lg, m, body.starter_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/advance")
def fantasy_advance(league_id: int, user: User = Depends(auth.get_current_user),
                    session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    if lg.owner_user_id != user.id and not auth.is_admin(user):
        raise HTTPException(403, "Solo el creador de la liga puede avanzar jornada")
    return fantasy_mod.advance(session, lg)


class ClauseBody(BaseModel):
    player_id: int


class RaiseClauseBody(BaseModel):
    player_id: int
    new_clause: float


@app.get("/api/fantasy/leagues/{league_id}/player/{player_id}")
def fantasy_player(league_id: int, player_id: int, jornada: Optional[int] = None,
                   user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    """Ficha del jugador. Con `jornada`, añade su partido de ese día (línea de acta)."""
    lg = _get_league(session, league_id)
    try:
        return fantasy_mod.player_detail(session, lg, player_id, jornada)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/fantasy/leagues/{league_id}/members/{member_id}/squad")
def fantasy_member_squad(league_id: int, member_id: int,
                         user: User = Depends(auth.get_current_user),
                         session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    try:
        return fantasy_mod.member_squad(session, lg, member_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/fantasy/leagues/{league_id}/clause")
def fantasy_clause(league_id: int, body: ClauseBody, user: User = Depends(auth.get_current_user),
                   session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.pay_clause(session, lg, m, body.player_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fantasy/leagues/{league_id}/clause/raise")
def fantasy_clause_raise(league_id: int, body: RaiseClauseBody,
                         user: User = Depends(auth.get_current_user),
                         session: Session = Depends(get_session)):
    lg = _get_league(session, league_id)
    m = _member_or_403(session, league_id, user.id)
    try:
        return fantasy_mod.raise_clause(session, lg, m, body.player_id, body.new_clause)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/fantasy/leagues/{league_id}/feed")
def fantasy_feed(league_id: int, user: User = Depends(auth.get_current_user),
                 session: Session = Depends(get_session)):
    _get_league(session, league_id)
    return fantasy_mod.feed(session, league_id, 50)
