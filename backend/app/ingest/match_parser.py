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


# ============================== play-by-play ==============================
# Vocabulario de acciones de la FEB tal como viene en el campo `action`.
PBP_ACTIONS = {
    "period",     # comienzo / fin de cuarto
    "subst",      # entra o sale de pista
    "shoot",      # tiro de campo (anotado o fallado), con valor en logParam6
    "fthrow",     # tiro libre
    "rebound",    # rebote (ofensivo/defensivo no viene: se deduce del tiro anterior)
    "assist",
    "lose",       # pérdida
    "recovery",   # robo
    "foul",
    "blockshot",  # tapón
}

_FOUL_KIND = re.compile(r"FALTA\s+(\w+)", re.IGNORECASE)


def _position(raw: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """'65.62|67.02' -> (65.62, 67.02). Coordenadas de pista completa, 0-100."""
    if not raw or "|" not in str(raw):
        return None, None
    try:
        x, y = str(raw).split("|")[:2]
        return float(x), float(y)
    except (ValueError, TypeError):
        return None, None


def parse_pbp(keyfacts: dict) -> list[dict]:
    """Normaliza el play-by-play de LiveStats, ya ordenado cronológicamente.

    La FEB lo devuelve del final hacia el principio; `num` es el orden real y es lo que
    manda, porque varias jugadas comparten el mismo reloj (un tiro, su rebote y la falta
    posterior pueden estar todos en el mismo segundo).
    """
    lines = (keyfacts.get("PLAYBYPLAY") or {}).get("LINES") or []
    out: list[dict] = []
    for ln in lines:
        action = (_clean(ln.get("action")) or "").lower()
        if not action:
            continue
        quarter = _int(ln.get("quarter")) or None
        clock = _clean(ln.get("time"))
        text = _clean(ln.get("text"))
        x, y = _position(ln.get("Position"))

        made: Optional[bool] = None
        points = 0
        detail: Optional[str] = None
        if action == "shoot":
            # logParam4: 1 anotado / 0 fallado · logParam6: valor del tiro (2 o 3).
            # El texto ("TIRO DE 3 ANOTADO") es el desempate si faltan los parámetros.
            value = _int(ln.get("logParam6")) or (3 if "DE 3" in (text or "") else 2)
            made = (str(ln.get("logParam4")).strip() == "1") if ln.get("logParam4") not in (None, "") \
                else ("ANOTADO" in (text or "").upper())
            points = value if made else 0
            detail = f"T{value}"
        elif action == "fthrow":
            made = (str(ln.get("logParam4")).strip() == "1") if ln.get("logParam4") not in (None, "") \
                else ("ANOTADO" in (text or "").upper())
            points = 1 if made else 0
            detail = "T1"
        elif action == "subst":
            # logParam3 lleva la licencia del que ENTRA; logParam2, la del que SALE.
            if ln.get("logParam3"):
                detail = "in"
            elif ln.get("logParam2"):
                detail = "out"
            else:
                detail = "in" if "Entra" in (text or "") else "out"
        elif action == "foul":
            m = _FOUL_KIND.search(text or "")
            detail = (m.group(1).lower() if m else None)
        elif action == "period":
            detail = "end" if "Fin" in (text or "") else "start"

        out.append({
            "num": _int(ln.get("num")),
            "quarter": quarter,
            "clock": clock,
            "seconds_elapsed": _seconds_elapsed(quarter or 0, clock),
            "team_index": (_int(ln.get("team")) - 1) if ln.get("team") else None,  # 1/2 -> 0/1
            "team_livestats_id": _clean(ln.get("idTeam")),
            "player_code": _clean(ln.get("idPlayer")),
            "action": action,
            "detail": detail,
            "made": made,
            "points": points,
            "score_home": _int(ln.get("scoreA"), None) if ln.get("scoreA") not in (None, "") else None,
            "score_away": _int(ln.get("scoreB"), None) if ln.get("scoreB") not in (None, "") else None,
            "x": x, "y": y,
            "text": text,
        })
    out.sort(key=lambda e: e["num"])
    return out
