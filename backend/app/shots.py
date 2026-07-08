"""Helpers de tiros: normalización a media pista y series para mapas/animación."""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from .models import Shot, PlayerMatchStat, Player


def to_halfcourt(x: float, y: float) -> tuple[float, float]:
    """Proyecta coordenadas de pista completa (0-100) a una media pista (0-100).

    Los dos equipos atacan canastas opuestas; reflejamos todo a la misma media pista
    para poder acumular tiros de un jugador/equipo en un único gráfico.
    """
    if x < 50:
        x = 100 - x
    hx = (x - 50) * 2.0          # 0 (centro) .. 100 (línea de fondo)
    hy = y                       # 0..100 a lo ancho
    return round(max(0.0, min(100.0, hx)), 2), round(max(0.0, min(100.0, hy)), 2)


def serialize_shot(s: Shot) -> dict:
    hx, hy = to_halfcourt(s.x, s.y)
    return {
        "hx": hx, "hy": hy, "made": s.made,
        "quarter": s.quarter, "clock": s.clock,
        "t": s.seconds_elapsed, "player_id": s.player_id,
        "is_home": s.is_home,
    }


def shots_for_team(session: Session, team_id: int) -> list[dict]:
    rows = session.exec(select(Shot).where(Shot.team_id == team_id)).all()
    return [serialize_shot(s) for s in rows]


def shots_for_player(session: Session, player_id: int) -> list[dict]:
    rows = session.exec(select(Shot).where(Shot.player_id == player_id)).all()
    return [serialize_shot(s) for s in rows]


def shots_for_match(session: Session, match_id: int, team_id: Optional[int] = None) -> list[dict]:
    q = select(Shot).where(Shot.match_id == match_id)
    if team_id is not None:
        q = q.where(Shot.team_id == team_id)
    rows = session.exec(q.order_by(Shot.seconds_elapsed)).all()
    return [serialize_shot(s) for s in rows]


def shot_zone_summary(shots: list[dict]) -> dict:
    """Resumen para el mapa: total, anotados, % por 2/3 aproximado según distancia al aro."""
    made = sum(1 for s in shots if s["made"])
    total = len(shots)
    return {
        "attempts": total,
        "made": made,
        "pct": round(100.0 * made / total, 1) if total else 0.0,
    }
