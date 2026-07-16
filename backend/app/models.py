"""Modelo de datos de PiScouting (SQLModel / SQLite).

Diseño orientado a análisis partido-a-partido, que es lo que permite calcular
métricas que NO aparecen en las estadísticas acumuladas de la FEB (p.ej. el +/-,
rachas, splits local/visitante, evolución temporal, mapas de tiro animados...).
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlmodel import SQLModel, Field, Relationship


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    name: Optional[str] = None
    team_id: Optional[int] = Field(default=None, foreign_key="teams.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Team(SQLModel, table=True):
    __tablename__ = "teams"

    id: Optional[int] = Field(default=None, primary_key=True)
    feb_url: str = Field(index=True, unique=True)  # Equipo.aspx?i=NNNN (identidad estable)
    feb_code: Optional[str] = Field(default=None, index=True)
    name: str = Field(index=True)
    logo: Optional[str] = None
    competition: str = Field(index=True)  # "1ª FEB", "2ª FEB", "3ª FEB"
    grupo: Optional[str] = Field(default=None, index=True)
    season: str = Field(index=True)

    # Clasificación (de la tabla de resultados acumulados)
    played: int = 0
    won: int = 0
    lost: int = 0
    points_for: int = 0
    points_against: int = 0

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Player(SQLModel, table=True):
    __tablename__ = "players"

    id: Optional[int] = Field(default=None, primary_key=True)
    feb_code: str = Field(index=True, unique=True)  # 'c' del enlace / id de LiveStats
    name: str = Field(index=True)
    photo_url: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Match(SQLModel, table=True):
    __tablename__ = "matches"

    id: Optional[int] = Field(default=None, primary_key=True)
    partido_id: str = Field(index=True, unique=True)  # id FEB del partido
    season: str = Field(index=True)
    competition: str = Field(index=True)
    grupo: Optional[str] = Field(default=None, index=True)
    jornada: Optional[str] = Field(default=None, index=True)
    jornada_num: Optional[int] = Field(default=None, index=True)
    match_date: Optional[date] = Field(default=None, index=True)

    home_team_id: Optional[int] = Field(default=None, foreign_key="teams.id", index=True)
    away_team_id: Optional[int] = Field(default=None, foreign_key="teams.id", index=True)
    home_score: Optional[int] = None
    away_score: Optional[int] = None

    # Detalle de cabecera (rellenado al ingerir el partido desde LiveStats)
    venue: Optional[str] = None
    referees: Optional[str] = None  # texto libre
    quarter_scores: Optional[str] = None  # JSON: [{"n":1,"home":17,"away":29}, ...]

    # Estado de ingesta del detalle (boxscore + tiros)
    status: str = Field(default="scheduled", index=True)  # scheduled|played|ingested
    ingested_at: Optional[datetime] = None


class PlayerMatchStat(SQLModel, table=True):
    """Línea de boxscore de un jugador en un partido. Incluye el +/- (plus_minus)."""
    __tablename__ = "player_match_stats"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id", index=True)
    team_id: int = Field(foreign_key="teams.id", index=True)
    player_id: int = Field(foreign_key="players.id", index=True)
    is_home: bool = Field(default=False, index=True)

    dorsal: Optional[str] = None
    starter: bool = False
    seconds: int = 0  # minutos jugados en segundos

    pts: int = 0
    t2m: int = 0
    t2a: int = 0
    t3m: int = 0
    t3a: int = 0
    tlm: int = 0
    tla: int = 0
    oreb: int = 0
    dreb: int = 0
    treb: int = 0
    ast: int = 0
    stl: int = 0
    tov: int = 0
    blk_for: int = 0
    blk_against: int = 0
    pf_committed: int = 0
    pf_received: int = 0
    dunks: int = 0
    val: int = 0
    plus_minus: int = 0


class FantasyLeague(SQLModel, table=True):
    """Liga fantasy. Se juega dentro de una 'conferencia' (competición + grupo): solo se
    pueden fichar jugadores de los equipos de ese grupo. La temporada se juega en modo
    repetición, avanzando jornada a jornada desde `start_jornada`."""
    __tablename__ = "fantasy_leagues"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    join_code: str = Field(index=True, unique=True)
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    season: str = Field(index=True)
    competition: str = Field(index=True)
    grupo: Optional[str] = Field(default=None, index=True)

    budget: float = 100.0
    squad_size: int = 10
    lineup_size: int = 5
    win_bonus: float = 4.0
    start_jornada: int = 0       # los precios de salida usan los partidos hasta aquí
    current_jornada: int = 0     # última jornada ya puntuada
    max_jornada: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FantasyMember(SQLModel, table=True):
    __tablename__ = "fantasy_members"

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="fantasy_leagues.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    manager_name: str
    budget_remaining: float = 100.0
    total_points: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FantasyPick(SQLModel, table=True):
    """Un jugador en la plantilla de un participante. `starter` marca los que puntúan."""
    __tablename__ = "fantasy_picks"

    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="fantasy_members.id", index=True)
    player_id: int = Field(foreign_key="players.id", index=True)
    buy_price: float = 0.0
    buy_jornada: int = 0
    starter: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Shot(SQLModel, table=True):
    """Tiro individual con coordenadas de media pista (para mapas estáticos y animados)."""
    __tablename__ = "shots"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id", index=True)
    team_id: int = Field(foreign_key="teams.id", index=True)
    player_id: Optional[int] = Field(default=None, foreign_key="players.id", index=True)
    is_home: bool = Field(default=False, index=True)

    x: float = 0.0  # porcentaje 0-100 (normalizado a media pista al servir)
    y: float = 0.0
    made: bool = False
    quarter: Optional[int] = Field(default=None, index=True)
    clock: Optional[str] = None  # "05:59" reloj del cuarto
    seconds_elapsed: Optional[int] = Field(default=None, index=True)  # segundos desde el inicio del partido
