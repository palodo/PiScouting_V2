"""Normaliza el payload de LiveStats de un partido a estructuras limpias.

Convierte HEADER / BOXSCORE / SHOTCHART en:
  - header: equipos, marcador, parciales por cuarto, sede, árbitros
  - players: lista de líneas de boxscore (incluye +/- via 'pllss')
  - shots: lista de tiros con coordenadas, cuarto, reloj y segundos transcurridos
"""
from __future__ import annotations

import re
from typing import Optional


def _int(v, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(float(str(v).replace(",", ".").strip()))
    except (ValueError, TypeError):
        return default


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _clock_to_seconds(clock: Optional[str]) -> Optional[int]:
    if not clock or ":" not in str(clock):
        return None
    try:
        mm, ss = str(clock).split(":")[:2]
        return int(mm) * 60 + int(ss)
    except (ValueError, TypeError):
        return None


def _seconds_elapsed(quarter: int, clock: Optional[str]) -> Optional[int]:
    """Segundos desde el inicio del partido (cuartos de 10', prórrogas de 5')."""
    remaining = _clock_to_seconds(clock)
    if remaining is None or quarter <= 0:
        return None
    if quarter <= 4:
        base, qlen = (quarter - 1) * 600, 600
    else:
        base, qlen = 2400 + (quarter - 5) * 300, 300
    return base + (qlen - remaining)


def parse_header(header: dict) -> dict:
    teams = header.get("TEAM") or []
    quarters = []
    q_container = header.get("QUARTERS") or {}
    for q in (q_container.get("QUARTER") or []):
        quarters.append({
            "n": _int(q.get("n")),
            "home": _int(q.get("scoreA")),
            "away": _int(q.get("scoreB")),
        })
    referees = " · ".join(
        r for r in (_clean(header.get(f"referee{i}")) for i in (1, 2, 3)) if r
    ) or None
    out = {
        "competition": _clean(header.get("competition")),
        "starttime": _clean(header.get("starttime")),
        "venue": _clean(header.get("field")),
        "place": _clean(header.get("place")),
        "referees": referees,
        "quarters": quarters,
        "teams": [],
    }
    for t in teams:
        out["teams"].append({
            "id": _clean(t.get("id")),
            "name": _clean(t.get("name")),
            "logo": _clean(t.get("logo")),
            "pts": _int(t.get("pts")),
        })
    return out


def parse_players(boxscore: dict) -> list[dict]:
    """Devuelve líneas de jugador con team_index (0/1) y team_id de LiveStats."""
    rows: list[dict] = []
    for team_index, team in enumerate(boxscore.get("TEAM") or []):
        team_id = _clean(team.get("id"))
        for p in (team.get("PLAYER") or []):
            pid = _clean(p.get("id"))
            if not pid:
                continue
            sta = str(p.get("sta") or "").strip().lower()
            rows.append({
                "team_index": team_index,
                "team_livestats_id": team_id,
                "player_code": pid,
                "name": _clean(p.get("name")),
                "dorsal": _clean(p.get("no")),
                "photo": _clean(p.get("logo")),
                "starter": sta in {"1", "*", "true", "s", "yes"},
                "seconds": _int(p.get("min")),
                "pts": _int(p.get("pts")),
                "t2m": _int(p.get("p2m")), "t2a": _int(p.get("p2a")),
                "t3m": _int(p.get("p3m")), "t3a": _int(p.get("p3a")),
                "tlm": _int(p.get("p1m")), "tla": _int(p.get("p1a")),
                "oreb": _int(p.get("ro")), "dreb": _int(p.get("rd")),
                "treb": _int(p.get("rt")) or _int(p.get("reb")),
                "ast": _int(p.get("assist")),
                "stl": _int(p.get("st")),
                "tov": _int(p.get("to")),
                "blk_for": _int(p.get("bs")),
                "blk_against": _int(p.get("tc")),
                "pf_committed": _int(p.get("pf")),
                "pf_received": _int(p.get("rf")),
                "dunks": _int(p.get("mt")),
                "val": _int(p.get("val")),
                "plus_minus": _int(p.get("pllss")),
            })
    return rows


def parse_shots(shotchart: dict) -> list[dict]:
    """Devuelve tiros con team_index (0/1), dorsal, coordenadas y tiempo."""
    shots: list[dict] = []
    for s in (shotchart.get("SHOTS") or []):
        x, y = s.get("x"), s.get("y")
        if x in (None, "") or y in (None, ""):
            continue
        try:
            fx, fy = float(x), float(y)
        except (ValueError, TypeError):
            continue
        quarter = _int(s.get("quarter"))
        clock = _clean(s.get("t"))
        shots.append({
            "team_index": _int(s.get("team")),
            "dorsal": _clean(s.get("player")),
            "x": fx,
            "y": fy,
            "made": str(s.get("m")) == "1",
            "quarter": quarter or None,
            "clock": clock,
            "seconds_elapsed": _seconds_elapsed(quarter, clock),
        })
    return shots


def parse_match(match_data: dict) -> dict:
    return {
        "header": parse_header(match_data.get("HEADER") or {}),
        "players": parse_players(match_data.get("BOXSCORE") or {}),
        "shots": parse_shots(match_data.get("SHOTCHART") or {}),
    }
