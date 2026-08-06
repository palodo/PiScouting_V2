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
    # Salto inicial real (UTC) cuando la FEB publica la hora, que es solo mientras el
    # partido está por jugarse. Es el reloj del fantasy: cierra el quinteto de la jornada.
    start_at: Optional[datetime] = Field(default=None, index=True)

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
    repetición, avanzando jornada a jornada desde `start_jornada`.

    Mercado estilo Biwenger: se abre un día y hora concretos de la semana, saca una tanda
    aleatoria de jugadores libres y se cierra pasadas `market_duration_h` horas resolviendo
    las pujas (gana la más alta)."""
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
    initial_squad: int = 5       # jugadores aleatorios al entrar (para poder jugar ya)
    win_bonus: float = 4.0
    # cláusula de rescisión: otro mánager puede llevarse a tu jugador pagándola.
    clause_factor: float = 2.0   # cláusula = valor · factor
    clause_lock_h: int = 24      # horas de gracia tras fichar (blindado)
    clause_raise_cost: float = 0.25  # coste de subir la cláusula (% de la subida)
    start_jornada: int = 0       # los precios de salida usan los partidos hasta aquí
    current_jornada: int = 0     # última jornada ya puntuada
    max_jornada: int = 0

    # --- mercado programado ---
    market_weekday: int = 4      # 0=lunes … 6=domingo (por defecto viernes)
    market_hour: int = 20        # hora local (Europe/Madrid) a la que abre
    market_duration_h: int = 24  # horas que permanece abierto
    market_size: int = 10        # jugadores que salen a subasta en cada tanda
    market_round: int = 0
    market_opens_at: Optional[datetime] = None   # UTC
    market_closes_at: Optional[datetime] = None  # UTC
    market_open: bool = False

    # --- calendario de la jornada ---
    # La liga vive en tres fases: MERCADO (se ficha, tanda nueva cada día) → ALINEACIÓN
    # (mercado cerrado, aún puedes tocar el quinteto) → JORNADA (se juega: todo bloqueado
    # hasta que acabe, aplazamientos incluidos). Ver fantasy.league_state().
    sim_mode: bool = True            # la temporada de la BBDD ya está jugada: calendario propio
    play_weekday: int = 5            # 0=lunes … 6=domingo: día del primer partido de la jornada
    play_hour: int = 18              # hora local (Europe/Madrid) del primer salto
    play_duration_h: int = 30        # lo que dura la jornada desde ese primer salto
    market_close_before_h: int = 24  # el mercado cierra estas horas antes (24 = el día antes)
    kickoff_at: Optional[datetime] = None  # UTC: primer salto de la jornada current+1

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
    clause: float = 0.0                                  # cláusula de rescisión
    clause_locked_until: Optional[datetime] = None       # blindaje tras fichar (UTC)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FantasyListing(SQLModel, table=True):
    """Un jugador sacado a subasta en una tanda del mercado."""
    __tablename__ = "fantasy_listings"

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="fantasy_leagues.id", index=True)
    round_no: int = Field(default=0, index=True)
    player_id: int = Field(foreign_key="players.id", index=True)
    price: float = 0.0            # precio de salida (puja mínima)
    resolved: bool = Field(default=False, index=True)
    winner_member_id: Optional[int] = Field(default=None, foreign_key="fantasy_members.id")
    sold_price: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FantasyBid(SQLModel, table=True):
    """Puja de un mánager por un jugador en subasta."""
    __tablename__ = "fantasy_bids"

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="fantasy_leagues.id", index=True)
    listing_id: int = Field(foreign_key="fantasy_listings.id", index=True)
    member_id: int = Field(foreign_key="fantasy_members.id", index=True)
    amount: float = 0.0
    status: str = Field(default="active", index=True)  # active|won|lost|cancelled
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FantasyEvent(SQLModel, table=True):
    """Actividad de la liga (fichajes, ventas, apertura/cierre de mercado, jornadas)."""
    __tablename__ = "fantasy_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="fantasy_leagues.id", index=True)
    kind: str = Field(default="info", index=True)  # market|signing|sale|jornada|join
    text: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class FantasyJornadaScore(SQLModel, table=True):
    """Lo que sumó cada mánager en una jornada concreta.

    Se guarda al puntuarla porque en el miembro solo queda el acumulado: sin esto no se
    puede mirar atrás ni saber quién ganó una jornada.
    """
    __tablename__ = "fantasy_jornada_scores"

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: int = Field(foreign_key="fantasy_leagues.id", index=True)
    member_id: int = Field(foreign_key="fantasy_members.id", index=True)
    jornada: int = Field(index=True)
    points: float = 0.0
    # Quinteto que estaba alineado al puntuar (JSON con los player_id). Sin esto, mirar una
    # jornada pasada usaba la plantilla de HOY y el desglose no cuadraba con el total.
    starters: Optional[str] = None
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
