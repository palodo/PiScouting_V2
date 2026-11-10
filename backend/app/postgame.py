"""Informe post-partido: toda la analítica de UN partido.

El scouting de equipo (`scouting.py`) mira una temporada entera; esto mira un partido con
lupa. La diferencia la hace el **play-by-play** (`PlayEvent`, que se baja del endpoint
KeyFacts de LiveStats): con el orden de las jugadas se reconstruye lo que el boxscore no
cuenta y que es lo que de verdad explica un partido:

  · posesión a posesión (de dónde sale cada punto: tras robo, tras rebote, tras canasta)
  · quién estaba en pista en cada momento (quintetos, parejas, tríos, +/- por unidad)
  · la evolución del marcador: rachas, máximas, cambios de líder, sequías
  · qué pasó justo antes y justo después de cada tiempo muerto

Dos reglas que no conviene romper:

1. **Lo validable se valida.** Recorriendo sustituciones y canastas del play-by-play salen
   los minutos y el +/- de cada jugador, y tienen que coincidir CLAVADOS con el boxscore
   oficial. `quality()` lo comprueba y el informe lo publica: si algo no cuadra, se dice.
2. **Lo estimado se etiqueta.** Las posesiones reales se cuentan (no se estiman); las
   fórmulas de Oliver (puntos producidos, Floor%, Stops) son estimaciones y van marcadas
   como tales, porque en un solo partido tienen muchísima varianza.

Sin play-by-play el informe sigue saliendo, pero solo con lo que da el boxscore: la clave
`available` dice qué secciones llevan dato.
"""
from __future__ import annotations

import json
import math
import re
from typing import Optional, Iterable

from sqlmodel import Session, select

from .models import Match, Team, Player, PlayerMatchStat, PlayEvent, Shot
from .cache import cached

# ============================================================================
# Geometría de la pista
# ============================================================================
# Las coordenadas de la FEB (0-100 sobre pista completa) NO cubren exactamente los 28x15 m
# reglamentarios: su lienzo es más ancho y menos profundo que la pista. Estos tres números
# son el resultado de calibrarlos contra el dato que no admite discusión: el VALOR de cada
# tiro (2 o 3) que viene en el propio play-by-play. Ajustando sobre 3.304 tiros de 25
# partidos de las tres categorías, el error de clasificar 2/3 por geometría baja del 2,69%
# (suponiendo 14x15 m) al 0,61% con estos valores. Ese 0,61% restante es ruido del dato.
COURT_L = 13.5   # metros que abarca hx 0..100 (de medio campo a la línea de fondo)
COURT_W = 16.3   # metros que abarca hy 0..100 (a lo ancho)
HOOP_D = 1.575   # profundidad del aro desde la línea de fondo (FIBA)

THREE_R = 6.75           # radio del arco
CORNER_Y = 6.60          # separación lateral de la línea recta de la esquina
CORNER_D = HOOP_D + math.sqrt(THREE_R ** 2 - CORNER_Y ** 2)  # donde el arco corta la recta
RESTRICTED_R = 1.25      # semicírculo de no-carga
KEY_HALF_W = 2.45        # media anchura de la zona (4,90 m)
KEY_D = 5.80             # fondo de la zona

ZONES = ["restringida", "pintura", "media", "triple_esquina", "triple_frontal"]
ZONE_LABEL = {
    "restringida": "Zona restringida",
    "pintura": "Resto de la pintura",
    "media": "Media distancia",
    "triple_esquina": "Triple de esquina",
    "triple_frontal": "Triple frontal",
}


def to_halfcourt(x: float, y: float) -> tuple[float, float]:
    """Pista completa (0-100) -> media pista. hx: 0 medio campo .. 100 fondo; hy: 0..100."""
    if x < 50:
        x = 100 - x
    return max(0.0, min(100.0, (x - 50) * 2.0)), max(0.0, min(100.0, y))


def court_metres(hx: float, hy: float) -> tuple[float, float]:
    """Media pista (0-100) -> (profundidad desde el fondo, desvío lateral) en metros."""
    return (100 - hx) / 100 * COURT_L, (hy - 50) / 100 * COURT_W


def shot_zone(hx: float, hy: float) -> str:
    d, dy = court_metres(hx, hy)
    if abs(dy) >= CORNER_Y and d <= CORNER_D:
        return "triple_esquina"
    dist = math.hypot(d - HOOP_D, dy)
    if dist >= THREE_R:
        return "triple_frontal"
    if dist <= RESTRICTED_R:
        return "restringida"
    if abs(dy) <= KEY_HALF_W and d <= KEY_D:
        return "pintura"
    return "media"


# ============================================================================
# Utilidades
# ============================================================================
def _d(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den else default


def _r(v: float, n: int = 1):
    """Redondea. Con n=0 devuelve un entero (119, no 119.0: es lo que se quiere imprimir)."""
    try:
        return int(round(float(v))) if n == 0 else round(float(v), n)
    except (TypeError, ValueError):
        return 0 if n == 0 else 0.0


def _mmss(seconds: Optional[int]) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _quarter_clock(ev) -> str:
    """'Q3 1:33' — el reloj tal como se ve en el pabellón."""
    if not ev.quarter:
        return "—"
    return f"Q{ev.quarter} {(ev.clock or '').lstrip('0') or '0:00'}"


def _clock_of(quarter: Optional[int], clock: Optional[str]) -> str:
    """'Q3 1:33'. Se quita solo el cero de los minutos ('00:36' -> '0:36')."""
    if not quarter:
        return "—"
    c = (clock or "").strip()
    if ":" in c:
        mm, _, ss = c.partition(":")
        c = f"{int(mm)}:{ss}"
    return f"Q{quarter} {c or '0:00'}"


# Partículas que no son un apellido por sí solas: se pegan a la palabra siguiente
# ("S. MC DONNELL" -> "MC DONNELL", no "MC").
_PARTICLE = {"MC", "MAC", "DE", "DEL", "LA", "LE", "LOS", "LAS", "VAN", "DER", "DEN",
             "VON", "DI", "DA", "DAS", "DOS", "SAN", "SANTA", "ST", "O", "EL", "AL", "BEN"}


def _short(name: Optional[str]) -> str:
    """'M. Martinez Hernandez' -> 'Martinez': el apellido, que es como se habla en el banquillo."""
    if not name:
        return "—"
    parts = [p for p in name.replace(".", ". ").split() if p]
    parts = [p for p in parts if not (len(p) <= 2 and p.endswith("."))]
    if not parts:
        return name
    out = [parts[0]]
    i = 1
    while i < len(parts) and out[-1].upper().strip("'") in _PARTICLE:
        out.append(parts[i])
        i += 1
    return " ".join(out)


# ============================================================================
# Posesiones reconstruidas desde el play-by-play
# ============================================================================
class Possession:
    """Una posesión real: desde que un equipo coge el balón hasta que lo pierde.

    `origin` dice CÓMO empezó, que es lo que permite separar la carrera del ataque
    estático: tras canasta recibida / tras rebote defensivo / tras robo / tras pérdida
    rival / inicio de cuarto.
    """
    __slots__ = ("team_id", "start", "end", "origin", "points", "oreb", "first_pts_at")

    def __init__(self, team_id: int, start: int, origin: str):
        self.team_id = team_id
        self.start = start
        self.end = start
        self.origin = origin
        self.points = 0
        self.oreb = 0
        self.first_pts_at: Optional[int] = None

    @property
    def seconds(self) -> int:
        return max(0, self.end - self.start)


ORIGIN_LABEL = {
    "canasta": "Tras canasta recibida",
    "rebote": "Tras rebote defensivo",
    "robo": "Tras robo",
    "perdida": "Tras pérdida rival",
    "inicio": "Inicio de cuarto",
}

# Acciones que mueven el balón (las que deciden de quién es la posesión).
_BALL = {"shoot", "fthrow", "rebound", "lose", "recovery", "period"}


def possessions(events: list[PlayEvent]) -> list[Possession]:
    """Reconstruye las posesiones recorriendo el play-by-play.

    La posesión cambia de manos con: canasta anotada (salvo que siga un tiro libre del
    mismo equipo: el adicional es la MISMA posesión), rebote defensivo, pérdida y final de
    cuarto. Un rebote ofensivo NO abre posesión nueva: la alarga, y eso es lo que permite
    contar los puntos de segunda oportunidad.
    """
    ball = [e for e in events if e.action in _BALL]
    out: list[Possession] = []
    cur: Optional[Possession] = None
    pending = "inicio"
    # Momento en que el balón cambió de manos. La posesión empieza AHÍ, no en la primera
    # acción ofensiva: si no, una posesión de 18 segundos que acaba en tiro mediría 0 y
    # cualquier canasta parecería una contra.
    pending_t = 0

    def close(t: int):
        nonlocal cur
        if cur is not None:
            cur.end = max(cur.end, t)
            out.append(cur)
            cur = None

    def open_for(team_id: int, t: int):
        nonlocal cur, pending
        if cur is not None and cur.team_id == team_id:
            return
        close(t)
        cur = Possession(team_id, min(pending_t, t), pending)
        cur.end = t
        pending = "inicio"

    for i, e in enumerate(ball):
        t = e.seconds_elapsed if e.seconds_elapsed is not None else (cur.end if cur else 0)
        nxt = ball[i + 1] if i + 1 < len(ball) else None

        if e.action == "period":
            close(t)
            pending, pending_t = "inicio", t
            continue

        if e.team_id is None:
            continue

        if e.action == "rebound":
            if cur is not None and e.team_id == cur.team_id:
                cur.oreb += 1
                cur.end = t
            else:
                close(t)
                pending, pending_t = "rebote", t
                open_for(e.team_id, t)
            continue

        if e.action == "recovery":
            # El robo llega justo después de la pérdida rival: afina el origen.
            if cur is None or cur.team_id != e.team_id:
                pending, pending_t = "robo", t
                open_for(e.team_id, t)
            continue

        if e.action == "lose":
            open_for(e.team_id, t)
            cur.end = t
            close(t)
            pending = "robo" if (nxt is not None and nxt.action == "recovery") else "perdida"
            pending_t = t
            continue

        if e.action in ("shoot", "fthrow"):
            open_for(e.team_id, t)
            cur.end = t
            if e.made:
                cur.points += e.points
                if cur.first_pts_at is None:
                    cur.first_pts_at = t
                # El adicional (y el 2º tiro libre) siguen siendo la misma posesión.
                same_team_ft = (nxt is not None and nxt.action == "fthrow"
                                and nxt.team_id == e.team_id)
                if not same_team_ft:
                    close(t)
                    pending, pending_t = "canasta", t
            continue

    close(ball[-1].seconds_elapsed if ball and ball[-1].seconds_elapsed is not None else 2400)
    return out


def _second_chance_points(events: list[PlayEvent]) -> dict[int, int]:
    """Puntos anotados DESPUÉS de un rebote ofensivo dentro de la misma posesión."""
    out: dict[int, int] = {}
    ball = [e for e in events if e.action in _BALL]
    live_team: Optional[int] = None
    after_oreb = False
    for i, e in enumerate(ball):
        if e.action == "period":
            live_team, after_oreb = None, False
            continue
        if e.team_id is None:
            continue
        if e.action == "rebound":
            if live_team is not None and e.team_id == live_team:
                after_oreb = True
            else:
                live_team, after_oreb = e.team_id, False
            continue
        if e.action in ("lose", "recovery"):
            live_team, after_oreb = (e.team_id if e.action == "recovery" else None), False
            continue
        if e.action in ("shoot", "fthrow"):
            if live_team != e.team_id:
                live_team, after_oreb = e.team_id, after_oreb if live_team == e.team_id else False
            if e.made:
                if after_oreb:
                    out[e.team_id] = out.get(e.team_id, 0) + e.points
                nxt = ball[i + 1] if i + 1 < len(ball) else None
                if not (nxt is not None and nxt.action == "fthrow" and nxt.team_id == e.team_id):
                    live_team, after_oreb = None, False
    return out


# ============================================================================
# Quién estaba en pista: tramos, quintetos, parejas y tríos
# ============================================================================
class Stint:
    """Un tramo de juego con los mismos diez jugadores en pista."""
    __slots__ = ("start", "end", "home", "away", "home_pts", "away_pts")

    def __init__(self, start: int, home: frozenset, away: frozenset):
        self.start = self.end = start
        self.home, self.away = home, away
        self.home_pts = self.away_pts = 0

    @property
    def seconds(self) -> int:
        return max(0, self.end - self.start)


def starters_from_pbp(events: list[PlayEvent]) -> set[int]:
    """Los cinco de cada equipo que arrancan el partido, según el play-by-play.

    Hace falta porque el boxscore de la FEB trae el campo de titularidad VACÍO (`sta` a
    null) en esta competición, así que `PlayerMatchStat.starter` es False para todos y sin
    esto la comparación titulares/suplentes no existiría. El play-by-play sí lo dice: los
    titulares entran con una sustitución en el 10:00 del primer cuarto.
    """
    out: set[int] = set()
    for e in events:
        if e.action == "period" and e.detail == "start" and (e.seconds_elapsed or 0) > 0:
            break
        if (e.action == "subst" and e.detail == "in" and e.player_id
                and (e.seconds_elapsed or 0) == 0):
            out.add(e.player_id)
    return out


def stints(events: list[PlayEvent], home_id: int) -> list[Stint]:
    """Trocea el partido en tramos con el mismo quinteto por bando.

    Los titulares entran con una sustitución en el 10:00 del Q1, así que no hace falta
    mirar el boxscore: el play-by-play se basta. Los minutos que salen de aquí cuadran
    con los oficiales (lo comprueba `quality`).
    """
    on_h: set[int] = set()
    on_a: set[int] = set()
    out: list[Stint] = []
    cur: Optional[Stint] = None
    last_t = 0

    def cut(t: int):
        nonlocal cur
        if cur is not None:
            cur.end = max(cur.end, t)
            if cur.seconds > 0 or cur.home_pts or cur.away_pts:
                out.append(cur)
        cur = Stint(t, frozenset(on_h), frozenset(on_a))

    for e in events:
        t = e.seconds_elapsed
        if t is None:
            continue
        if e.action == "subst" and e.player_id:
            side = on_h if e.is_home else on_a
            if e.detail == "in":
                if e.player_id in side:
                    continue
                cut(t)
                side.add(e.player_id)
                cur.home, cur.away = frozenset(on_h), frozenset(on_a)
            else:
                if e.player_id not in side:
                    continue
                cut(t)
                side.discard(e.player_id)
                cur.home, cur.away = frozenset(on_h), frozenset(on_a)
            last_t = t
        elif e.action in ("shoot", "fthrow") and e.made and e.points:
            if cur is None:
                cur = Stint(t, frozenset(on_h), frozenset(on_a))
            cur.end = max(cur.end, t)
            if e.is_home:
                cur.home_pts += e.points
            else:
                cur.away_pts += e.points
            last_t = t
    if cur is not None:
        end = max(last_t, max((e.seconds_elapsed or 0) for e in events))
        cur.end = max(cur.end, end)
        out.append(cur)
    return out


def _unit_rows(sts: list[Stint], side: str, names: dict[int, str], min_seconds: int,
               limit: int) -> list[dict]:
    agg: dict[frozenset, dict] = {}
    for s in sts:
        unit = s.home if side == "home" else s.away
        if len(unit) != 5:
            continue
        d = agg.setdefault(unit, {"sec": 0, "for": 0, "against": 0})
        d["sec"] += s.seconds
        d["for"] += s.home_pts if side == "home" else s.away_pts
        d["against"] += s.away_pts if side == "home" else s.home_pts
    rows = [{
        "players": sorted(_short(names.get(p, "?")) for p in unit),
        "seconds": d["sec"], "min": _mmss(d["sec"]),
        "pts_for": d["for"], "pts_against": d["against"],
        "plus_minus": d["for"] - d["against"],
        "partial": f"{d['for']}-{d['against']}",
    } for unit, d in agg.items()]
    rows.sort(key=lambda r: -r["seconds"])
    return [r for r in rows if r["seconds"] >= min_seconds][:limit], len(agg)


def _combo_rows(sts: list[Stint], side: str, names: dict[int, str], size: int,
                min_seconds: int, limit: int) -> list[dict]:
    """Parejas (size=2) y tríos (size=3): más minutos juntos que un quinteto, así que la
    señal es menos ruidosa que la del quinteto concreto."""
    from itertools import combinations
    agg: dict[tuple, dict] = {}
    for s in sts:
        unit = s.home if side == "home" else s.away
        if len(unit) < size:
            continue
        pf = s.home_pts if side == "home" else s.away_pts
        pa = s.away_pts if side == "home" else s.home_pts
        for combo in combinations(sorted(unit), size):
            d = agg.setdefault(combo, {"sec": 0, "for": 0, "against": 0})
            d["sec"] += s.seconds
            d["for"] += pf
            d["against"] += pa
    rows = [{
        "players": [_short(names.get(p, "?")) for p in combo],
        "seconds": d["sec"], "min": _r(d["sec"] / 60, 1),
        "plus_minus": d["for"] - d["against"],
    } for combo, d in agg.items() if d["sec"] >= min_seconds]
    rows.sort(key=lambda r: (-r["seconds"]))
    return rows[:limit]


# ============================================================================
# Métricas de caja (equipo y jugador)
# ============================================================================
_BOX_KEYS = ("pts", "t2m", "t2a", "t3m", "t3a", "tlm", "tla", "oreb", "dreb", "treb",
             "ast", "stl", "tov", "blk_for", "blk_against", "pf_committed", "pf_received",
             "val", "seconds")


def _team_totals(rows: list[PlayerMatchStat]) -> dict:
    t = {k: 0 for k in _BOX_KEYS}
    for r in rows:
        for k in _BOX_KEYS:
            t[k] += getattr(r, k)
    t["fga"] = t["t2a"] + t["t3a"]
    t["fgm"] = t["t2m"] + t["t3m"]
    t["minutes"] = t["seconds"] / 60
    return t


def game_score(s) -> float:
    """Game Score de Hollinger. Es un PER de UN partido: resume la línea en un número."""
    fgm = s.t2m + s.t3m
    fga = s.t2a + s.t3a
    return (s.pts + 0.4 * fgm - 0.7 * fga - 0.4 * (s.tla - s.tlm) + 0.7 * s.oreb
            + 0.3 * s.dreb + s.stl + 0.7 * s.ast + 0.7 * s.blk_for - 0.4 * s.pf_committed
            - s.tov)


def oliver(s, team: dict, opp: dict) -> dict:
    """Producción individual de *Basketball on Paper* (Dean Oliver), implementación
    `oliver_bref_v1` (la de Basketball Reference).

    Devuelve puntos producidos, posesiones usadas, eficiencia ofensiva individual, Floor%
    y Stops. En UN partido son ESTIMACIONES con mucha varianza: valen para ordenar y para
    elegir vídeo, no para sentenciar a nadie. El informe las etiqueta como tales.
    """
    mp, t_mp = s.seconds / 60, team["minutes"]
    fgm, fga = s.t2m + s.t3m, s.t2a + s.t3a
    ftm, fta = s.tlm, s.tla
    pts, ast, orb, tov = s.pts, s.ast, s.oreb, s.tov

    if not mp or not t_mp or not team["fga"]:
        return {"pprod": 0.0, "poss": 0.0, "ortg": None, "floor": None, "stops": 0.0,
                "usg": 0.0, "ts": None}

    t_fgm, t_fga, t_ftm, t_fta = team["fgm"], team["fga"], team["tlm"], team["tla"]
    t_ast, t_orb, t_tov, t_pts, t_3pm = team["ast"], team["oreb"], team["tov"], team["pts"], team["t3m"]

    q_ast = ((mp / (t_mp / 5)) * (1.14 * _d(t_ast - ast, t_fgm))) + (
        _d(_d(t_ast, t_mp) * mp * 5 - ast, _d(t_fgm, t_mp) * mp * 5 - fgm)
        * (1 - mp / (t_mp / 5)))
    fg_part = fgm * (1 - 0.5 * _d(pts - ftm, 2 * fga) * q_ast)
    ast_part = 0.5 * _d((t_pts - t_ftm) - (pts - ftm), 2 * (t_fga - fga)) * ast
    ft_part = (1 - (1 - _d(ftm, fta)) ** 2) * 0.4 * fta
    t_sc_poss = t_fgm + (1 - (1 - _d(t_ftm, t_fta)) ** 2) * t_fta * 0.4
    t_orb_pct = _d(t_orb, t_orb + opp["dreb"])
    t_play_pct = _d(t_sc_poss, t_fga + t_fta * 0.4 + t_tov)
    den = (1 - t_orb_pct) * t_play_pct + t_orb_pct * (1 - t_play_pct)
    t_orb_w = _d((1 - t_orb_pct) * t_play_pct, den)
    orb_part = orb * t_orb_w * t_play_pct

    shrink = 1 - _d(t_orb, t_sc_poss) * t_orb_w * t_play_pct
    sc_poss = (fg_part + ast_part + ft_part) * shrink + orb_part
    fgx = (fga - fgm) * (1 - 1.07 * t_orb_pct)
    ftx = ((1 - _d(ftm, fta)) ** 2) * 0.4 * fta
    tot_poss = sc_poss + fgx + ftx + tov

    pp_fg = 2 * (fgm + 0.5 * s.t3m) * (1 - 0.5 * _d(pts - ftm, 2 * fga) * q_ast)
    pp_ast = (2 * _d(t_fgm - fgm + 0.5 * (t_3pm - s.t3m), t_fgm - fgm) * 0.5
              * _d((t_pts - t_ftm) - (pts - ftm), 2 * (t_fga - fga)) * ast)
    pp_orb = orb * t_orb_w * t_play_pct * _d(t_pts, t_sc_poss)
    pprod = (pp_fg + pp_ast + ftm) * shrink + pp_orb

    # --- defensa ---
    d_or_pct = _d(opp["oreb"], opp["oreb"] + team["dreb"])
    d_fg_pct = _d(opp["fgm"], opp["fga"])
    fmwt = _d(d_fg_pct * (1 - d_or_pct),
              d_fg_pct * (1 - d_or_pct) + (1 - d_fg_pct) * d_or_pct)
    stops1 = s.stl + s.blk_for * fmwt * (1 - 1.07 * d_or_pct) + s.dreb * (1 - fmwt)
    stops2 = ((_d(opp["fga"] - opp["fgm"] - team["blk_for"], t_mp) * fmwt * (1 - 1.07 * d_or_pct)
               + _d(opp["tov"] - team["stl"], t_mp)) * mp
              + _d(s.pf_committed, team["pf_committed"]) * 0.4 * opp["tla"]
              * (1 - _d(opp["tlm"], opp["tla"])) ** 2)
    stops = stops1 + stops2

    usg_den = t_fga + 0.44 * t_fta + t_tov
    usg = 100 * _d((fga + 0.44 * fta + tov) * (t_mp / 5), mp * usg_den)
    ts = _d(pts, 2 * (fga + 0.44 * fta))

    return {
        "pprod": _r(pprod, 1),
        "poss": _r(tot_poss, 1),
        "ortg": _r(100 * _d(pprod, tot_poss), 0) if tot_poss > 0 else None,
        "floor": _r(100 * _d(sc_poss, tot_poss), 0) if tot_poss > 0 else None,
        "stops": _r(stops, 1),
        "usg": _r(usg, 1),
        "ts": _r(100 * ts, 1) if (fga + fta) else None,
    }


# ============================================================================
# Informe
# ============================================================================
@cached
def build(session: Session, match_id: int) -> dict:
    """Informe post-partido completo de un partido. Dict serializable (API y PDF)."""
    m = session.get(Match, match_id)
    if not m or not m.home_team_id or not m.away_team_id:
        return {}
    home = session.get(Team, m.home_team_id)
    away = session.get(Team, m.away_team_id)

    stats = session.exec(select(PlayerMatchStat)
                         .where(PlayerMatchStat.match_id == match_id)).all()
    events = session.exec(select(PlayEvent).where(PlayEvent.match_id == match_id)
                          .order_by(PlayEvent.num)).all()
    shots = session.exec(select(Shot).where(Shot.match_id == match_id)).all()

    pids = {s.player_id for s in stats} | {e.player_id for e in events if e.player_id}
    names = {p.id: p.name for p in session.exec(
        select(Player).where(Player.id.in_(list(pids)))).all()} if pids else {}
    codes = {p.id: p.feb_code for p in session.exec(
        select(Player).where(Player.id.in_(list(pids)))).all()} if pids else {}

    hrows = [s for s in stats if s.team_id == m.home_team_id]
    arows = [s for s in stats if s.team_id == m.away_team_id]
    ht, at = _team_totals(hrows), _team_totals(arows)

    quarters = json.loads(m.quarter_scores) if m.quarter_scores else []
    hs = m.home_score if m.home_score is not None else ht["pts"]
    aw = m.away_score if m.away_score is not None else at["pts"]

    rep: dict = {
        "match": {
            "match_id": m.id, "partido_id": m.partido_id,
            "competition": m.competition, "grupo": m.grupo, "season": m.season,
            "jornada": m.jornada, "jornada_num": m.jornada_num,
            "date": m.match_date.isoformat() if m.match_date else None,
            "start_at": m.start_at.isoformat() if m.start_at else None,
            "venue": m.venue, "referees": m.referees,
            "quarters": quarters,
            "halftime": _halftime(quarters),
            "home": {"team_id": home.id, "name": home.name, "logo": home.logo, "score": hs},
            "away": {"team_id": away.id, "name": away.name, "logo": away.logo, "score": aw},
            "winner": "home" if hs > aw else ("away" if aw > hs else None),
            "margin": abs(hs - aw),
        },
        "available": {
            "box": bool(stats),
            "pbp": bool(events),
            "shots": bool(shots),
        },
    }
    if not stats:
        rep["advanced"] = None
        return rep

    # ---------------- avanzada / four factors ----------------
    real_h, real_a = None, None
    poss_list = possessions(events) if events else []
    if poss_list:
        real_h = sum(1 for p in poss_list if p.team_id == m.home_team_id)
        real_a = sum(1 for p in poss_list if p.team_id == m.away_team_id)
    rep["advanced"] = _advanced(ht, at, real_h, real_a)

    # ---------------- boxscore ----------------
    starters = starters_from_pbp(events) if events else set()
    rep["box"] = {
        "home": _box_rows(hrows, names, codes, starters),
        "away": _box_rows(arows, names, codes, starters),
        "totals": {"home": _box_total(ht), "away": _box_total(at)},
    }

    # ---------------- producción individual ----------------
    rep["production"] = {
        "home": _production(hrows, ht, at, names),
        "away": _production(arows, at, ht, names),
    }

    # ---------------- impacto, banquillo y faltas ----------------
    rep["impact"] = _impact(hrows, arows, ht, at, names, events, m, starters)
    rep["starters"] = sorted(starters)

    # ---------------- tiro ----------------
    rep["shooting"] = _shooting(events, shots, m, ht, at)

    # ---------------- play-by-play ----------------
    if events:
        rep["flow"] = _flow(events, m, hs, aw)
        rep["phases"] = _phases(events, m)
        rep["possessions"] = _possession_economy(poss_list, events, m, ht, at)
        rep["lineups"] = _lineups(events, m, names)
        rep["quality"] = quality(events, stats, m, hs, aw)
    else:
        rep["flow"] = rep["phases"] = rep["possessions"] = rep["lineups"] = None
        rep["quality"] = {"level": "básico", "verified": [], "estimated": [
            "Sin play-by-play: no hay posesiones reales, quintetos ni evolución del marcador."]}

    # ---------------- narrativa ----------------
    # Los números SUELTOS se sirven como números (60.3) para que quien consuma la API
    # pueda operar con ellos; en los textos ya redactados se escriben a la española
    # (60,3), porque ahí son prosa y se leen tal cual en pantalla y en el PDF.
    rep["summary"] = _es(_summary(rep))
    rep["keys"] = _es(_keys(rep))
    rep["quality"] = _es(rep["quality"])
    return rep


_DEC = re.compile(r"(?<=\d)\.(?=\d)")


def _es(value):
    """Pasa los decimales de los textos ya redactados a coma, sin tocar los números."""
    if isinstance(value, str):
        return _DEC.sub(",", value)
    if isinstance(value, dict):
        return {k: _es(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_es(v) for v in value]
    return value


def _halftime(quarters: list[dict]) -> Optional[str]:
    if len(quarters) < 2:
        return None
    h = sum(q.get("home") or 0 for q in quarters[:2])
    a = sum(q.get("away") or 0 for q in quarters[:2])
    return f"{h}-{a}"


# ---------------------------------------------------------------- avanzada
def _advanced(ht: dict, at: dict, real_h: Optional[int], real_a: Optional[int]) -> dict:
    def est(t: dict) -> float:
        return t["fga"] + 0.44 * t["tla"] - t["oreb"] + t["tov"]

    est_h, est_a = est(ht), est(at)
    # El ritmo del PARTIDO (media de los dos) es el denominador de las eficiencias: las dos
    # juegan el mismo partido, así que comparar 'puntos por 100' con denominadores distintos
    # mete una diferencia que no existe.
    pace = ((real_h + real_a) / 2) if (real_h and real_a) else ((est_h + est_a) / 2)

    def side(t: dict, opp: dict, real: Optional[int], own_est: float) -> dict:
        own = real if real else own_est
        return {
            "poss_real": real,
            "poss_est": _r(own_est, 1),
            "off_rtg": _r(100 * _d(t["pts"], pace), 1),
            "def_rtg": _r(100 * _d(opp["pts"], pace), 1),
            "net_rtg": _r(100 * _d(t["pts"] - opp["pts"], pace), 1),
            "efg": _r(100 * _d(t["fgm"] + 0.5 * t["t3m"], t["fga"]), 1),
            "ts": _r(100 * _d(t["pts"], 2 * (t["fga"] + 0.44 * t["tla"])), 1),
            "tov_pct": _r(100 * _d(t["tov"], own), 1),
            "orb_pct": _r(100 * _d(t["oreb"], t["oreb"] + opp["dreb"]), 1),
            "drb_pct": _r(100 * _d(t["dreb"], t["dreb"] + opp["oreb"]), 1),
            "ftr": _r(100 * _d(t["tla"], t["fga"]), 1),
            "three_rate": _r(100 * _d(t["t3a"], t["fga"]), 1),
            "ast_pct": _r(100 * _d(t["ast"], t["fgm"]), 1),
            "ast_to": _r(_d(t["ast"], t["tov"]), 2),
            "pts": t["pts"],
        }

    return {"pace": _r(pace, 1),
            "home": side(ht, at, real_h, est_h),
            "away": side(at, ht, real_a, est_a)}


# ---------------------------------------------------------------- boxscore
def _box_rows(rows: list[PlayerMatchStat], names: dict, codes: dict,
              starters: set[int]) -> list[dict]:
    out = []
    for s in sorted(rows, key=lambda r: (-r.seconds, -r.pts)):
        out.append({
            "player_id": s.player_id, "name": names.get(s.player_id, "—"),
            "short": _short(names.get(s.player_id)), "feb_code": codes.get(s.player_id),
            "dorsal": s.dorsal,
            "starter": (s.player_id in starters) if starters else bool(s.starter),
            "min": _mmss(s.seconds), "seconds": s.seconds,
            "pts": s.pts, "t2": f"{s.t2m}/{s.t2a}", "t3": f"{s.t3m}/{s.t3a}",
            "tl": f"{s.tlm}/{s.tla}", "tc": f"{s.t2m + s.t3m}/{s.t2a + s.t3a}",
            "oreb": s.oreb, "dreb": s.dreb, "treb": s.treb, "ast": s.ast,
            "stl": s.stl, "tov": s.tov, "blk": s.blk_for, "pf": s.pf_committed,
            "val": s.val, "plus_minus": s.plus_minus,
            "gmsc": _r(game_score(s), 1),
        })
    return out


def _box_total(t: dict) -> dict:
    return {"pts": t["pts"], "tc": f"{t['fgm']}/{t['fga']}",
            "t3": f"{t['t3m']}/{t['t3a']}", "tl": f"{t['tlm']}/{t['tla']}",
            "oreb": t["oreb"], "dreb": t["dreb"], "treb": t["treb"], "ast": t["ast"],
            "stl": t["stl"], "tov": t["tov"], "blk": t["blk_for"], "pf": t["pf_committed"]}


def _production(rows: list[PlayerMatchStat], team: dict, opp: dict, names: dict) -> list[dict]:
    out = []
    for s in sorted(rows, key=lambda r: -r.seconds):
        if s.seconds <= 0:
            continue
        o = oliver(s, team, opp)
        enough = s.seconds >= 600  # Floor% y eficiencia solo con 10+ minutos
        out.append({
            "player_id": s.player_id, "short": _short(names.get(s.player_id)),
            "dorsal": s.dorsal, "min": _r(s.seconds / 60, 1),
            "usg": o["usg"], "ts": o["ts"], "gmsc": _r(game_score(s), 1),
            "pprod": o["pprod"], "poss": o["poss"],
            "ortg": o["ortg"] if enough else None,
            "floor": o["floor"] if enough else None,
            "stops": o["stops"], "plus_minus": s.plus_minus,
        })
    return out


# ---------------------------------------------------------------- impacto
def _impact(hrows, arows, ht, at, names, events, m, starters: set[int]) -> dict:
    def top3(rows):
        ranked = sorted(rows, key=lambda s: -game_score(s))[:3]
        return [{"short": _short(names.get(s.player_id)), "min": _mmss(s.seconds),
                 "gmsc": _r(game_score(s), 1), "val": s.val, "pts": s.pts,
                 "plus_minus": s.plus_minus} for s in ranked]

    def is_starter(s) -> bool:
        return (s.player_id in starters) if starters else bool(s.starter)

    def unit(rows, want: bool, team_pts: int):
        sel = [s for s in rows if is_starter(s) == want]
        sec = sum(s.seconds for s in sel)
        pts = sum(s.pts for s in sel)
        fga = sum(s.t2a + s.t3a for s in sel)
        fta = sum(s.tla for s in sel)
        return {
            "group": "Titulares" if want else "Suplentes",
            "min": _r(sec / 60, 0), "pts": pts,
            "pts40": _r(_d(pts * 40 * 5, sec / 60), 1) if sec else 0.0,
            "ts": _r(100 * _d(pts, 2 * (fga + 0.44 * fta)), 1),
            "tov": sum(s.tov for s in sel),
            "share": _r(100 * _d(pts, team_pts), 0),
        }

    # Las faltas de un equipo se leen por lo que le dan al rival: por eso cada bloque
    # lleva los tiros libres que lanzó EL OTRO.
    fouls = {"home": _fouls(events, m, True, arows, names),
             "away": _fouls(events, m, False, hrows, names)} if events else None

    return {
        "top": {"home": top3(hrows), "away": top3(arows)},
        "units": {
            "home": [unit(hrows, True, ht["pts"]), unit(hrows, False, ht["pts"])],
            "away": [unit(arows, True, at["pts"]), unit(arows, False, at["pts"])],
        },
        "fouls": fouls,
    }


def _fouls(events, m, is_home: bool, opp_rows, names) -> dict:
    """Faltas por cuarto, cuándo entró el rival en bonus y quién se cargó pronto.

    Dos faltas en la primera mitad es la señal clásica de banquillo forzado: se marca con
    el minuto en que llegó la segunda.
    """
    by_q = {}
    bonus_at = None
    for e in events:
        if e.action != "foul" or e.is_home != is_home or not e.quarter:
            continue
        if e.detail in ("técnica", "tecnica", "antideportiva") and e.player_id is None:
            continue
        by_q[e.quarter] = by_q.get(e.quarter, 0) + 1
        if by_q[e.quarter] == 5 and bonus_at is None:
            bonus_at = _clock_of(e.quarter, e.clock)

    # Segunda falta personal de cada jugador antes del descanso
    count: dict[int, int] = {}
    early = []
    for e in events:
        if e.action != "foul" or e.is_home != is_home or not e.player_id:
            continue
        if e.quarter and e.quarter > 2:
            continue
        count[e.player_id] = count.get(e.player_id, 0) + 1
        if count[e.player_id] == 2:
            early.append({"short": _short(names.get(e.player_id)),
                          "at": _clock_of(e.quarter, e.clock)})
    return {
        "by_quarter": [by_q.get(q, 0) for q in (1, 2, 3, 4)],
        "total": sum(by_q.values()),
        "opp_bonus_at": bonus_at,
        "early_two": early,
        "opp_ft_attempts": sum(r.tla for r in opp_rows),
        "opp_ft_made": sum(r.tlm for r in opp_rows),
    }


# ---------------------------------------------------------------- tiro
def _shooting(events, shots, m, ht, at) -> dict:
    """Perfil de tiro por zonas.

    Prefiere el play-by-play al shotchart: trae las mismas coordenadas PERO con el valor
    del tiro (2 o 3) ya puesto por la FEB, así que no hay que adivinarlo por geometría.
    """
    pbp_shots = [e for e in events if e.action == "shoot" and e.x is not None]
    rows: list[dict] = []
    if pbp_shots:
        for e in pbp_shots:
            hx, hy = to_halfcourt(e.x, e.y)
            value = 3 if (e.detail == "T3") else 2
            zone = shot_zone(hx, hy)
            # El valor oficial manda sobre la geometría cuando se contradicen.
            if value == 3 and zone not in ("triple_esquina", "triple_frontal"):
                zone = "triple_frontal"
            elif value == 2 and zone in ("triple_esquina", "triple_frontal"):
                zone = "media"
            rows.append({"hx": hx, "hy": hy, "made": bool(e.made), "value": value,
                         "zone": zone, "is_home": bool(e.is_home),
                         "quarter": e.quarter, "player_id": e.player_id})
    elif shots:
        for s in shots:
            hx, hy = to_halfcourt(s.x, s.y)
            zone = shot_zone(hx, hy)
            rows.append({"hx": hx, "hy": hy, "made": bool(s.made),
                         "value": 3 if zone.startswith("triple") else 2,
                         "zone": zone, "is_home": bool(s.is_home),
                         "quarter": s.quarter, "player_id": s.player_id})

    def zone_table(is_home: bool) -> list[dict]:
        mine = [r for r in rows if r["is_home"] == is_home]
        total = len(mine) or 1
        out = []
        for z in ZONES:
            zr = [r for r in mine if r["zone"] == z]
            made = sum(1 for r in zr if r["made"])
            pts = sum(r["value"] for r in zr if r["made"])
            out.append({
                "zone": z, "label": ZONE_LABEL[z],
                "made": made, "att": len(zr),
                "pct": _r(100 * _d(made, len(zr)), 1),
                "pps": _r(_d(pts, len(zr)), 2),
                "share": _r(100 * len(zr) / total, 0),
            })
        return out

    def halves(is_home: bool, tot: dict) -> list[dict]:
        out = []
        for label, qs in (("1ª mitad", (1, 2)), ("2ª mitad", (3, 4, 5, 6))):
            hr = [r for r in rows if r["is_home"] == is_home and r["quarter"] in qs]
            made = sum(1 for r in hr if r["made"])
            t3 = [r for r in hr if r["value"] == 3]
            ft = [e for e in events if e.action == "fthrow" and bool(e.is_home) == is_home
                  and e.quarter in qs]
            out.append({
                "half": label,
                "tc": f"{made}/{len(hr)}",
                "t3": f"{sum(1 for r in t3 if r['made'])}/{len(t3)}",
                "tl": f"{sum(1 for e in ft if e.made)}/{len(ft)}",
                "pts": sum(r["value"] for r in hr if r["made"]) + sum(1 for e in ft if e.made),
            })
        return out

    return {
        "zones": {"home": zone_table(True), "away": zone_table(False)},
        "halves": {"home": halves(True, ht), "away": halves(False, at)},
        "shots": {"home": [r for r in rows if r["is_home"]],
                  "away": [r for r in rows if not r["is_home"]]},
        "source": "play-by-play" if pbp_shots else ("shotchart" if shots else None),
    }


# ---------------------------------------------------------------- evolución
def _flow(events, m, final_h: int, final_a: int) -> dict:
    """Evolución del marcador: serie, mando, máximas, cambios de líder y sequías."""
    series = [{"t": 0, "home": 0, "away": 0, "diff": 0, "quarter": 1}]
    scoring = []
    h = a = 0
    for e in events:
        if e.action not in ("shoot", "fthrow") or not e.made or not e.points:
            continue
        t = e.seconds_elapsed or 0
        if e.is_home:
            h += e.points
        else:
            a += e.points
        # El marcador que publica la FEB manda si viene; si no, el acumulado.
        if e.score_home is not None and e.score_away is not None:
            h, a = e.score_home, e.score_away
        series.append({"t": t, "home": h, "away": a, "diff": h - a, "quarter": e.quarter,
                       "clock": e.clock})
        scoring.append({"t": t, "is_home": bool(e.is_home), "pts": e.points,
                        "quarter": e.quarter, "clock": e.clock, "home": h, "away": a})

    end_t = max((e.seconds_elapsed or 0) for e in events) if events else 2400
    series.append({"t": end_t, "home": final_h, "away": final_a,
                   "diff": final_h - final_a, "quarter": series[-1]["quarter"],
                   "clock": "00:00"})

    # tiempo con ventaja
    lead_h = lead_a = tied = 0
    for prev, nxt in zip(series, series[1:]):
        dt = max(0, nxt["t"] - prev["t"])
        if prev["diff"] > 0:
            lead_h += dt
        elif prev["diff"] < 0:
            lead_a += dt
        else:
            tied += dt

    max_h = max(series, key=lambda s: s["diff"])
    max_a = min(series, key=lambda s: s["diff"])

    changes = ties = 0
    last_sign = 0
    for s in series:
        sign = (s["diff"] > 0) - (s["diff"] < 0)
        if sign == 0 and last_sign != 0:
            ties += 1
        if sign != 0 and last_sign != 0 and sign != last_sign:
            changes += 1
        if sign != 0:
            last_sign = sign

    def drought(is_home: bool) -> dict:
        ts = [0] + [s["t"] for s in scoring if s["is_home"] == is_home] + [end_t]
        best, at = 0, None
        for p, n in zip(ts, ts[1:]):
            if n - p > best:
                best, at = n - p, p
        q = next((s["quarter"] for s in scoring if s["t"] >= (at or 0)), None)
        clock = next((s["clock"] for s in scoring if s["t"] >= (at or 0)), None)
        return {"seconds": best, "label": _mmss(best), "from": _clock_of(q, clock)}

    return {
        "series": series,
        "scoring": scoring,
        "lead_time": {"home": lead_h, "away": lead_a, "tied": tied,
                      "home_label": _mmss(lead_h), "away_label": _mmss(lead_a)},
        "max_lead": {
            "home": {"pts": max(0, max_h["diff"]),
                     "at": _clock_of(max_h.get("quarter"), max_h.get("clock"))},
            "away": {"pts": max(0, -max_a["diff"]),
                     "at": _clock_of(max_a.get("quarter"), max_a.get("clock"))},
        },
        "lead_changes": changes, "ties": ties,
        "droughts": {"home": drought(True), "away": drought(False)},
        "runs": _runs(scoring),
    }


def _runs(scoring: list[dict], threshold: int = 6) -> list[dict]:
    """Rachas sin respuesta de `threshold` puntos o más.

    El marcador de la racha se da en el momento JUSTO ANTES de la primera canasta, que es
    como se cuenta un parcial en la pizarra.
    """
    runs: list[dict] = []
    cur = None
    for s in scoring:
        if cur and cur["is_home"] == s["is_home"]:
            cur["pts"] += s["pts"]
            cur["to"] = s
        else:
            if cur and cur["pts"] >= threshold:
                runs.append(cur)
            cur = {"is_home": s["is_home"], "pts": s["pts"], "from": s, "to": s,
                   "before": {"home": s["home"] - (s["pts"] if s["is_home"] else 0),
                              "away": s["away"] - (0 if s["is_home"] else s["pts"])}}
    if cur and cur["pts"] >= threshold:
        runs.append(cur)
    out = []
    for r in sorted(runs, key=lambda r: -r["pts"])[:6]:
        out.append({
            "is_home": r["is_home"], "pts": r["pts"],
            "run": f"{r['pts']}-0",
            "from_score": f"{r['before']['home']}-{r['before']['away']}",
            "to_score": f"{r['to']['home']}-{r['to']['away']}",
            "from_clock": _clock_of(r["from"]["quarter"], r["from"]["clock"]),
            "to_clock": _clock_of(r["to"]["quarter"], r["to"]["clock"]),
        })
    return out


# ---------------------------------------------------------------- fases
def _phases(events, m) -> dict:
    """Cómo se reparte cada cuarto (arranque / tramo central / cierre) y los tiempos muertos."""
    def pts_between(q: int, lo: int, hi: int) -> tuple[int, int]:
        """Puntos entre los segundos [lo, hi) DEL CUARTO q."""
        h = a = 0
        for e in events:
            if e.action not in ("shoot", "fthrow") or not e.made or not e.points:
                continue
            if e.quarter != q:
                continue
            base = (q - 1) * 600 if q <= 4 else 2400 + (q - 5) * 300
            inq = (e.seconds_elapsed or 0) - base
            if lo <= inq < hi:
                if e.is_home:
                    h += e.points
                else:
                    a += e.points
        return h, a

    qs = sorted({e.quarter for e in events if e.quarter})
    rows = []
    for q in qs:
        length = 600 if q <= 4 else 300
        op = pts_between(q, 0, 180)
        mid = pts_between(q, 180, length - 120)
        close = pts_between(q, length - 120, length + 1)
        tot = pts_between(q, 0, length + 1)
        rows.append({
            "quarter": q,
            "open3": f"{op[0]}-{op[1]}", "open3_diff": op[0] - op[1],
            "mid": f"{mid[0]}-{mid[1]}", "mid_diff": mid[0] - mid[1],
            "close2": f"{close[0]}-{close[1]}", "close2_diff": close[0] - close[1],
            "total": f"{tot[0]}-{tot[1]}", "total_diff": tot[0] - tot[1],
        })

    return {"quarters": rows, "timeouts": _timeouts(events, m)}


def _timeouts(events, m) -> list[dict]:
    """Qué pasó dos minutos antes y dos minutos después de cada tiempo muerto.

    Muestra pequeñísima (4-6 por partido): es descriptivo, sirve para elegir vídeo, no para
    medir a un entrenador. El informe lo dice.
    """
    scoring = [e for e in events if e.action in ("shoot", "fthrow") and e.made and e.points]
    out = []
    for e in events:
        if e.action != "timeout":
            continue
        t = e.seconds_elapsed or 0
        mine = bool(e.is_home)

        def window(lo: int, hi: int) -> tuple[int, int]:
            f = ag = 0
            for s in scoring:
                st = s.seconds_elapsed or 0
                if lo <= st < hi:
                    if bool(s.is_home) == mine:
                        f += s.points
                    else:
                        ag += s.points
            return f, ag

        before = window(t - 120, t)
        after = window(t, t + 120)
        prev = [s for s in scoring if (s.seconds_elapsed or 0) <= t
                and s.score_home is not None]
        score_h = prev[-1].score_home if prev else 0
        score_a = prev[-1].score_away if prev else 0
        out.append({
            "is_home": mine,
            "at": _clock_of(e.quarter, e.clock),
            "score": f"{score_h}-{score_a}",
            "before": f"{before[0]}-{before[1]}",
            "after": f"{after[0]}-{after[1]}",
            "swing": (after[0] - after[1]) - (before[0] - before[1]),
        })
    return out


# ---------------------------------------------------------------- economía
def _possession_economy(poss: list[Possession], events, m, ht, at) -> dict:
    """De dónde salen los puntos: la diferencia entre ganar la carrera y ganar en estático."""
    if not poss:
        return None
    second = _second_chance_points(events)

    def side(team_id: int) -> dict:
        mine = [p for p in poss if p.team_id == team_id]
        total = len(mine) or 1
        by_origin = []
        # "inicio" va incluido (aunque sean pocas posesiones) para que la suma de la tabla
        # cuadre con los puntos del equipo: una tabla de orígenes que no suma el marcador
        # obliga a desconfiar de todo lo demás.
        for key in ("canasta", "rebote", "robo", "perdida", "inicio"):
            sel = [p for p in mine if p.origin == key]
            if key == "inicio" and not sel:
                continue
            pts = sum(p.points for p in sel)
            by_origin.append({
                "origin": key, "label": ORIGIN_LABEL[key],
                "poss": len(sel), "pts": pts,
                "ppp": _r(_d(pts, len(sel)), 2),
            })
        fast = sum(p.points for p in mine
                   if p.origin in ("robo", "rebote", "perdida")
                   and p.first_pts_at is not None and (p.first_pts_at - p.start) <= 8)
        off_tov = sum(p.points for p in mine if p.origin in ("robo", "perdida"))
        return {
            "poss": len(mine),
            "points": sum(p.points for p in mine),
            "ppp": _r(_d(sum(p.points for p in mine), len(mine)), 2),
            "empty": sum(1 for p in mine if p.points == 0),
            "empty_pct": _r(100 * _d(sum(1 for p in mine if p.points == 0), total), 0),
            "second_chance": second.get(team_id, 0),
            "second_chance_poss": sum(1 for p in mine if p.oreb),
            "off_turnovers": off_tov,
            "off_turnovers_poss": sum(1 for p in mine if p.origin in ("robo", "perdida")),
            "fast_break": fast,
            "by_origin": by_origin,
            "avg_seconds": _r(_d(sum(p.seconds for p in mine), len(mine)), 1),
        }

    return {"home": side(m.home_team_id), "away": side(m.away_team_id)}


# ---------------------------------------------------------------- quintetos
def _lineups(events, m, names) -> dict:
    sts = stints(events, m.home_team_id)
    if not sts:
        return None

    def side(key: str) -> dict:
        units, distinct = _unit_rows(sts, key, names, min_seconds=108, limit=8)
        starting = None
        for s in sts:
            unit = s.home if key == "home" else s.away
            if len(unit) == 5:
                sec = sum(x.seconds for x in sts
                          if (x.home if key == "home" else x.away) == unit)
                pm = sum((x.home_pts - x.away_pts) if key == "home"
                         else (x.away_pts - x.home_pts) for x in sts
                         if (x.home if key == "home" else x.away) == unit)
                starting = {"players": sorted(_short(names.get(p, "?")) for p in unit),
                            "min": _r(sec / 60, 1), "plus_minus": pm}
                break
        return {
            "units": units,
            "distinct": distinct,
            "starting": starting,
            "pairs": _combo_rows(sts, key, names, 2, min_seconds=480, limit=6),
            "trios": _combo_rows(sts, key, names, 3, min_seconds=360, limit=6),
        }

    return {"home": side("home"), "away": side("away")}


# ---------------------------------------------------------------- calidad
def quality(events, stats, m, final_h: int, final_a: int) -> dict:
    """Qué se ha podido validar y qué es estimación. Sin esto, el informe sería opaco.

    Lo importante: los minutos y el +/- que salen del play-by-play tienen que coincidir
    con los del acta. Si no coinciden, el informe lo dice en vez de disimularlo.
    """
    sts = stints(events, m.home_team_id)
    mins: dict[int, int] = {}
    pm: dict[int, int] = {}
    for s in sts:
        for p in s.home:
            mins[p] = mins.get(p, 0) + s.seconds
            pm[p] = pm.get(p, 0) + (s.home_pts - s.away_pts)
        for p in s.away:
            mins[p] = mins.get(p, 0) + s.seconds
            pm[p] = pm.get(p, 0) + (s.away_pts - s.home_pts)

    ok_min = sum(1 for s in stats if abs(mins.get(s.player_id, 0) - s.seconds) <= 3)
    ok_pm = sum(1 for s in stats if pm.get(s.player_id, 0) == s.plus_minus)
    n = len(stats)

    # marcador reconstruido
    h = sum(e.points for e in events if e.action in ("shoot", "fthrow") and e.made and e.is_home)
    a = sum(e.points for e in events
            if e.action in ("shoot", "fthrow") and e.made and e.is_home is False)

    verified = [
        f"Marcador reconstruido {h}-{a} · oficial {final_h}-{final_a}"
        + (": coinciden." if (h, a) == (final_h, final_a) else ": NO coinciden."),
        f"Minutos validados {ok_min}/{n} · +/- validado {ok_pm}/{n}",
        f"Posesiones contadas una a una sobre {len(events)} jugadas del play-by-play",
    ]

    estimated = []
    for label, is_home in (("local", True), ("visitante", False)):
        pbp_tov = sum(1 for e in events if e.action == "lose" and e.is_home is is_home)
        box_tov = sum(s.tov for s in stats if s.is_home is is_home)
        if pbp_tov != box_tov:
            estimated.append(f"Pérdidas del {label}: {pbp_tov} en play-by-play frente a "
                             f"{box_tov} en boxscore (las de equipo no tienen dueño).")
        pbp_reb = sum(1 for e in events if e.action == "rebound" and e.is_home is is_home)
        box_reb = sum(s.treb for s in stats if s.is_home is is_home)
        if pbp_reb != box_reb:
            estimated.append(f"Rebotes del {label}: {pbp_reb} en play-by-play frente a "
                             f"{box_reb} en boxscore.")
    coords = sum(1 for e in events if e.action == "shoot" and e.x is not None)
    shots_n = sum(1 for e in events if e.action == "shoot")
    estimated.append(f"Tiros con coordenadas: {coords} de {shots_n}.")
    estimated.append("Puntos producidos, Floor% y Stops son estimaciones de Oliver "
                     "(oliver_bref_v1): en un solo partido tienen mucha varianza.")
    estimated.append("Sin defensor directo: el play-by-play no dice quién defiende, "
                     "ni el tipo de jugada, ni si el tiro iba contestado.")

    level = "completo" if (ok_min == n and ok_pm == n and (h, a) == (final_h, final_a)) \
        else ("parcial" if events else "básico")
    return {"level": level, "verified": verified, "estimated": estimated,
            "minutes_ok": ok_min, "pm_ok": ok_pm, "players": n}


# ---------------------------------------------------------------- narrativa
def _summary(rep: dict) -> dict:
    """Resumen ejecutivo, redactado a partir de los números (sin texto genérico).

    Mismo criterio que en el resto del informe: cada frase lleva su número detrás.
    """
    mt = rep["match"]
    adv = rep["advanced"]
    h, a = mt["home"], mt["away"]
    hn, an = h["name"], a["name"]
    ah, aa = adv["home"], adv["away"]
    win_home = (h["score"] or 0) > (a["score"] or 0)
    win, los = (hn, an) if win_home else (an, hn)
    wa, la = (ah, aa) if win_home else (aa, ah)

    # titular: lo que más separó a los dos equipos
    gaps = [
        ("efg", abs(ah["efg"] - aa["efg"]), f"{win} tiró mejor (eFG% {wa['efg']} frente a {la['efg']})"),
        ("tov", abs(ah["tov_pct"] - aa["tov_pct"]),
         f"{win} cuidó más el balón (pérdidas en el {wa['tov_pct']}% de sus posesiones, "
         f"{la['tov_pct']}% el rival)" if wa["tov_pct"] < la["tov_pct"]
         else f"{win} ganó pese a perder más balones ({wa['tov_pct']}% frente a {la['tov_pct']}%)"),
        ("orb", abs(ah["orb_pct"] - aa["orb_pct"]),
         f"{win} mandó en el rebote ofensivo (ORB% {wa['orb_pct']} frente a {la['orb_pct']})"
         if wa["orb_pct"] > la["orb_pct"] else
         f"{los} ganó el rebote ofensivo (ORB% {la['orb_pct']}) y aun así perdió"),
        ("ftr", abs(ah["ftr"] - aa["ftr"]),
         f"{win} vivió más de la línea (FTr {wa['ftr']} frente a {la['ftr']})"
         if wa["ftr"] > la["ftr"] else f"{los} tiró más libres (FTr {la['ftr']}) sin rentabilizarlo"),
    ]
    gaps.sort(key=lambda g: -g[1])
    headline = gaps[0][2]

    lead = (f"Con {adv['pace']} posesiones, {hn} anotó {ah['off_rtg']} puntos por 100 y "
            f"{an}, {aa['off_rtg']}. {headline}.")

    cards = [
        {"label": "Resultado", "value": f"{h['score']}-{a['score']}",
         "foot": f"diferencia {mt['margin']}"},
        {"label": "eFG%", "value": f"{ah['efg']}%", "foot": f"{an} {aa['efg']}%"},
        {"label": "Pérdidas", "value": f"{rep['box']['totals']['home']['tov']}-"
                                       f"{rep['box']['totals']['away']['tov']}",
         "foot": f"TOV% {ah['tov_pct']}%"},
    ]
    pos = rep.get("possessions")
    if pos:
        cards.append({"label": "Pts 2ª oportunidad",
                      "value": f"{pos['home']['second_chance']}-{pos['away']['second_chance']}",
                      "foot": f"reb. of. {rep['box']['totals']['home']['oreb']}-"
                              f"{rep['box']['totals']['away']['oreb']}"})
        cards.append({"label": "Pts tras pérdida",
                      "value": f"{pos['home']['off_turnovers']}-{pos['away']['off_turnovers']}",
                      "foot": f"en {pos['home']['off_turnovers_poss']}-"
                              f"{pos['away']['off_turnovers_poss']} posesiones"})
        cards.append({"label": "Pts rápidos (hasta 8 s)",
                      "value": f"{pos['home']['fast_break']}-{pos['away']['fast_break']}",
                      "foot": f"posesión media {pos['home']['avg_seconds']}s"})

    decided = []
    flow = rep.get("flow")
    if flow:
        if flow["runs"]:
            r = flow["runs"][0]
            who = hn if r["is_home"] else an
            decided.append({
                "title": f"Parcial de {r['run']} de {who}",
                "text": f"De {r['from_score']} ({r['from_clock']}) a {r['to_score']} "
                        f"({r['to_clock']}).",
            })
        lt = flow["lead_time"]
        ahead, ahead_t = (hn, lt["home_label"]) if lt["home"] >= lt["away"] else (an, lt["away_label"])
        decided.append({
            "title": "Mando en el marcador",
            "text": f"{ahead} fue por delante {ahead_t} de los 40 minutos, con "
                    f"{flow['lead_changes']} cambio(s) de líder y {flow['ties']} empate(s).",
        })

    signals = []
    if pos:
        signals.append({"title": "Carrera",
                        "text": f"Puntos rápidos (hasta 8 s): {pos['home']['fast_break']} de {hn} "
                                f"por {pos['away']['fast_break']} de {an}."})
        signals.append({"title": "Posesiones vacías",
                        "text": f"{pos['home']['empty']}/{pos['home']['poss']} de {hn} y "
                                f"{pos['away']['empty']}/{pos['away']['poss']} de {an} "
                                f"acabaron sin puntos."})
    # Sin play-by-play no se sabe quién salió de inicio (el acta de la FEB no lo publica),
    # así que contarían todos como suplentes: mejor callarse que decir una falsedad.
    if rep.get("starters"):
        units = rep["impact"]["units"]
        signals.append({"title": "Banquillos",
                        "text": f"{units['home'][1]['pts']}-{units['away'][1]['pts']}; "
                                f"los suplentes pusieron el {units['home'][1]['share']}% de "
                                f"{hn} y el {units['away'][1]['share']}% de {an}."})
    if not decided:
        decided.append({
            "title": "Sin play-by-play",
            "text": "Este partido todavía no tiene las jugadas descargadas, así que el "
                    "informe va solo con el acta: no hay rachas, quintetos ni posesiones.",
        })

    return {"headline": headline, "lead": lead, "cards": cards,
            "decided": decided, "signals": signals}


def _keys(rep: dict) -> dict:
    """Claves para preparar a cada equipo: qué quitarle, dónde atacarle y a quién vigilar."""
    mt, adv = rep["match"], rep["advanced"]
    pos = rep.get("possessions")
    out = {}
    for side, other in (("home", "away"), ("away", "home")):
        tot = rep["box"]["totals"][side]
        a_me, a_opp = adv[side], adv[other]
        top = rep["impact"]["top"][side]
        zones = {z["zone"]: z for z in rep["shooting"]["zones"][side]}

        take = []
        if pos and pos[side]["fast_break"] >= 12:
            take.append(f"la carrera ({pos[side]['fast_break']} puntos rápidos, "
                        f"{tot['stl']} robos)")
        if a_me["orb_pct"] >= 30:
            take.append(f"el rebote ofensivo (ORB% {a_me['orb_pct']}, {tot['oreb']} capturados)")
        best3 = zones.get("triple_frontal")
        if best3 and best3["att"] >= 10 and best3["pct"] >= 33:
            take.append(f"el triple frontal ({best3['made']}/{best3['att']})")
        if a_me["ftr"] >= 35:
            take.append(f"la línea ({tot['tl']} desde el tiro libre)")
        if not take:
            take.append(f"su mejor zona: {max(zones.values(), key=lambda z: z['att'])['label'].lower()}")

        attack = []
        if a_me["tov_pct"] >= 18:
            attack.append(f"su manejo ({tot['tov']} pérdidas, TOV% {a_me['tov_pct']})")
        if a_me["drb_pct"] <= 70:
            attack.append(f"su rebote defensivo (cedió {rep['box']['totals'][other]['oreb']} ofensivos)")
        rest = zones.get("restringida")
        if rest and rest["pct"] and rest["pct"] < 55:
            attack.append(f"el aro, donde no cerró bien ({rest['made']}/{rest['att']} suyo)")
        flow = rep.get("flow")
        if flow:
            d = flow["droughts"][side]
            if d["seconds"] >= 150:
                attack.append(f"sus parones: {d['label']} sin anotar desde {d['from']}")
        if not attack:
            attack.append(f"su eficiencia ({a_me['off_rtg']} puntos por 100 posesiones)")

        watch = [f"{t['short']} ({t['gmsc']} Game Score, {t['pts']} pts, {t['plus_minus']:+d})"
                 for t in top[:2]]
        bench = rep["impact"]["units"][side][1]
        if bench["pts"] >= 25:
            watch.append(f"su banquillo ({bench['pts']} puntos)")

        out[side] = {
            "team": mt[side]["name"],
            "take_away": take[:3],
            "attack": attack[:3],
            "watch": watch[:3],
        }
    return out


# ============================================================================
# Listado de partidos de un equipo con informe disponible
# ============================================================================
def team_matches(session: Session, team_id: int) -> list[dict]:
    """Partidos jugados del equipo, para elegir de cuál se quiere el informe."""
    rows = session.exec(
        select(Match).where((Match.home_team_id == team_id) | (Match.away_team_id == team_id))
    ).all()
    ids = {t for m in rows for t in (m.home_team_id, m.away_team_id) if t}
    teams = {t.id: t for t in session.exec(select(Team).where(Team.id.in_(list(ids)))).all()} \
        if ids else {}
    out = []
    for m in rows:
        if m.home_score is None or m.away_score is None:
            continue
        is_home = m.home_team_id == team_id
        opp = teams.get(m.away_team_id if is_home else m.home_team_id)
        mine = m.home_score if is_home else m.away_score
        their = m.away_score if is_home else m.home_score
        out.append({
            "match_id": m.id, "jornada": m.jornada, "jornada_num": m.jornada_num,
            "date": m.match_date.isoformat() if m.match_date else None,
            "is_home": is_home,
            "opponent": opp.name if opp else "—",
            "opponent_id": opp.id if opp else None,
            "opponent_logo": opp.logo if opp else None,
            "score": f"{mine}-{their}",
            "result": "V" if mine > their else "D",
            "margin": mine - their,
            "ready": bool(m.pbp_events),          # ya tiene play-by-play descargado
            "detail": m.status == "ingested",     # tiene boxscore y tiros
        })
    out.sort(key=lambda r: (r["jornada_num"] if r["jornada_num"] is not None else 999,
                            r["date"] or ""))
    return out
