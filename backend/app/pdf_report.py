"""Informe de scouting en PDF (horizontal, visual, muy informativo).

Reproduce la estructura de los informes clásicos de PI Scouting sobre el rival:
portada, últimos partidos, estadísticas de equipo (básicas y avanzadas) con ranking
dentro del grupo y coloreadas por rendimiento, comparativa de ratings, posicionamiento
competitivo, fichas individuales, hoja de comentarios, jugadores destacados con
fortalezas/debilidades (derivadas de los datos, sin texto genérico) y rankings de
jugadores y de equipos.

Toda la analítica se calcula a partir del boxscore partido-a-partido; las fórmulas
avanzadas están validadas contra los informes originales (FTr, PPP, AST%, FT-eff...).
"""
from __future__ import annotations

import io
from typing import Optional

import requests
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image as RLImage,
)
from sqlmodel import Session, select

from .config import DATA_DIR, FEB_BASE
from .models import Team, Player, PlayerMatchStat
from . import scouting as scouting_mod

# ------------------------------ paleta ------------------------------
NAVY = colors.HexColor("#28344A")      # cabeceras / títulos
NAVY_D = colors.HexColor("#1B2436")
INK = colors.HexColor("#20293A")
BLUE = colors.HexColor("#2F6FE0")      # valores destacados en fichas
MUTED = colors.HexColor("#7B8698")
FAINT = colors.HexColor("#AEB7C6")
G_BG, G_BD = colors.HexColor("#E4F5E9"), colors.HexColor("#37A75B")   # bueno
Y_BG, Y_BD = colors.HexColor("#FFF3D6"), colors.HexColor("#E4A62A")   # medio
R_BG, R_BD = colors.HexColor("#FBE3E0"), colors.HexColor("#D6463C")   # flojo
HL_BG = colors.HexColor("#FBE1E4")     # fila del equipo objetivo (rosa suave)
LINE = colors.HexColor("#D9DEE8")
LINE_SOFT = colors.HexColor("#E9ECF3")
ZEBRA = colors.HexColor("#F5F7FA")
WIN = colors.HexColor("#1F9D55")
LOSS = colors.HexColor("#D6463C")

PW, PH = landscape(A4)
MARGIN = 14 * mm
CONTENT_W = PW - 2 * MARGIN

PHOTO_CACHE = DATA_DIR / "player_photos_cache"
PHOTO_CACHE.mkdir(exist_ok=True)
LOGO_CACHE = DATA_DIR / "team_logos_cache"
LOGO_CACHE.mkdir(exist_ok=True)

_styles = getSampleStyleSheet()


def _p(text, size=9, color=INK, bold=False, align=TA_LEFT, leading=None, font=None):
    return Paragraph(str(text), ParagraphStyle(
        "x", parent=_styles["Normal"], fontSize=size,
        fontName=font or ("Helvetica-Bold" if bold else "Helvetica"),
        textColor=color, alignment=align, leading=leading or size + 2))


def _page_title(text):
    return _p(text.upper(), 27, NAVY, bold=True, align=TA_CENTER)


def _section(text):
    return _p(text.upper(), 13, NAVY, bold=True, align=TA_CENTER)


# ============================ imágenes ============================
def _fetch_image(url, cache_path) -> Optional[Image.Image]:
    if not url:
        return None
    if cache_path.exists():
        try:
            return Image.open(io.BytesIO(cache_path.read_bytes()))
        except Exception:
            pass
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if r.status_code == 200 and len(r.content) > 800:
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            cache_path.write_bytes(r.content)
            return img
    except Exception:
        pass
    return None


def _logo_pil(team) -> Optional[Image.Image]:
    tid = team.get("team_id") if isinstance(team, dict) else team.id
    url = team.get("logo") if isinstance(team, dict) else team.logo
    img = _fetch_image(url, LOGO_CACHE / f"{tid}.img")
    if not img:
        return None
    bg = Image.new("RGBA", img.size, (255, 255, 255, 0))
    bg.paste(img, (0, 0), img.convert("RGBA"))
    return bg


def _logo_flowable(team, w=44):
    pil = _logo_pil(team)
    if not pil:
        return None
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return RLImage(buf, width=w * mm, height=w * mm, kind="proportional", hAlign="CENTER")


def player_photo(feb_code) -> Optional[io.BytesIO]:
    if not feb_code:
        return None
    cached = PHOTO_CACHE / f"{feb_code}.jpg"
    if cached.exists():
        try:
            return io.BytesIO(cached.read_bytes())
        except Exception:
            pass
    try:
        r = requests.get(f"https://imagenes.feb.es/Foto.aspx?c={feb_code}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if r.status_code == 200 and len(r.content) > 1200:
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            if img.size[0] >= 40:
                img.save(cached, "JPEG", quality=85)
                return io.BytesIO(cached.read_bytes())
    except Exception:
        pass
    return None


def _photo_flowable(feb_code, w, h):
    ph = player_photo(feb_code)
    return RLImage(ph, width=w * mm, height=h * mm) if ph else _blank(w, h)


def _blank(w, h):
    t = Table([[""]], colWidths=[w * mm], rowHeights=[h * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E9ECF3")),
                           ("BOX", (0, 0), (-1, -1), 0.5, LINE)]))
    return t


# ============================ analítica de grupo ============================
_KEYS = ["pts", "ast", "t3m", "t3a", "treb", "oreb", "dreb", "stl", "tov", "pts_against",
         "fg2", "fg3", "ft", "tc", "efg",
         "off_rtg", "def_rtg", "pace", "net", "ts", "three_par", "ftr",
         "tov_pct", "ast_to", "orb_pct", "drb_pct", "ppp", "ast_pct", "ft_eff"]
# métricas donde MENOR es mejor (para el ranking)
_LOWER_BETTER = {"pts_against", "tov", "def_rtg", "tov_pct"}


def _agg_zero():
    return {k: 0 for k in ("pts", "t2m", "t2a", "t3m", "t3a", "tlm", "tla",
                           "oreb", "dreb", "treb", "ast", "stl", "tov")}


def group_metrics(session: Session, team: dict):
    """Métricas por equipo dentro del grupo del equipo objetivo.

    Devuelve (por_equipo, orden) donde por_equipo[team_id] = {name, logo, team_id, **métricas}.
    Las métricas dependientes del rival (DefRtg, ORB%, DRB%) usan el boxscore del oponente.
    """
    q = select(Team).where(Team.competition == team["competition"], Team.season == team["season"])
    if team.get("grupo"):
        q = q.where(Team.grupo == team["grupo"])
    teams = session.exec(q).all()
    ids = {t.id for t in teams}
    names = {t.id: t.name for t in teams}
    logos = {t.id: t.logo for t in teams}

    stats = session.exec(select(PlayerMatchStat).where(PlayerMatchStat.team_id.in_(list(ids)))).all()
    season_tot: dict[int, dict] = {tid: _agg_zero() for tid in ids}
    games: dict[int, set] = {tid: set() for tid in ids}
    match_tot: dict[int, dict[int, dict]] = {}       # match -> team -> agg
    for s in stats:
        d = season_tot[s.team_id]
        for k in d:
            d[k] += getattr(s, k)
        games[s.team_id].add(s.match_id)
        mt = match_tot.setdefault(s.match_id, {}).setdefault(s.team_id, _agg_zero())
        for k in mt:
            mt[k] += getattr(s, k)

    def poss(a):
        return a["t2a"] + a["t3a"] + 0.44 * a["tla"] - a["oreb"] + a["tov"]

    out: dict[int, dict] = {}
    for tid in ids:
        a = season_tot[tid]
        g = len(games[tid]) or 1
        fga = a["t2a"] + a["t3a"]
        fgm = a["t2m"] + a["t3m"]
        # oponente acumulado sobre los partidos del equipo
        opp = _agg_zero()
        for mid in games[tid]:
            for otid, oa in match_tot.get(mid, {}).items():
                if otid != tid:
                    for k in opp:
                        opp[k] += oa[k]
        p = poss(a)
        op = poss(opp) or 1
        p1 = p or 1
        m = {
            "team_id": tid, "name": names[tid], "logo": logos[tid], "games": g,
            "pts": a["pts"] / g, "ast": a["ast"] / g, "t3m": a["t3m"] / g, "t3a": a["t3a"] / g,
            "treb": a["treb"] / g, "oreb": a["oreb"] / g, "dreb": a["dreb"] / g,
            "stl": a["stl"] / g, "tov": a["tov"] / g, "pts_against": opp["pts"] / g,
            "fg2": _pct(a["t2m"], a["t2a"]), "fg3": _pct(a["t3m"], a["t3a"]),
            "ft": _pct(a["tlm"], a["tla"]), "tc": _pct(fgm, fga),
            "efg": (fgm + 0.5 * a["t3m"]) / fga * 100 if fga else 0,
            "off_rtg": a["pts"] / p1 * 100, "def_rtg": opp["pts"] / op * 100,
            "pace": p / g, "ts": a["pts"] / (2 * (fga + 0.44 * a["tla"])) * 100 if fga else 0,
            "three_par": a["t3a"] / fga if fga else 0, "ftr": a["tla"] / fga if fga else 0,
            "tov_pct": a["tov"] / p1 * 100, "ast_to": a["ast"] / a["tov"] if a["tov"] else 0,
            "orb_pct": a["oreb"] / (a["oreb"] + opp["dreb"]) * 100 if (a["oreb"] + opp["dreb"]) else 0,
            "drb_pct": a["dreb"] / (a["dreb"] + opp["oreb"]) * 100 if (a["dreb"] + opp["oreb"]) else 0,
            "ppp": a["pts"] / p1, "ast_pct": a["ast"] / fgm * 100 if fgm else 0,
            "ft_eff": a["tlm"] / fga if fga else 0,
        }
        m["net"] = m["off_rtg"] - m["def_rtg"]
        out[tid] = m
    return out, len(ids)


def _pct(m, a):
    return round(100.0 * m / a, 1) if a else 0.0


def _rank_of(metrics: dict, tid: int, key: str):
    order = sorted(metrics.values(), key=lambda x: x[key], reverse=(key not in _LOWER_BETTER))
    for i, m in enumerate(order, 1):
        if m["team_id"] == tid:
            return i
    return None


def _rank_list(metrics: dict, key: str):
    return sorted(metrics.values(), key=lambda x: x[key], reverse=(key not in _LOWER_BETTER))


# ============================ jugadores (ficha ampliada) ============================
def rich_roster(session: Session, team_id: int) -> list[dict]:
    rows = session.exec(
        select(PlayerMatchStat, Player).join(Player, Player.id == PlayerMatchStat.player_id)
        .where(PlayerMatchStat.team_id == team_id)
    ).all()
    by: dict[int, dict] = {}
    tt = {k: 0 for k in ("t2a", "t3a", "tla", "tov")}
    tg = set()
    for st, pl in rows:
        d = by.setdefault(pl.id, {"player_id": pl.id, "name": pl.name, "feb_code": pl.feb_code,
                                  "games": 0, **{k: 0 for k in (
                                      "sec", "pts", "val", "pm", "t2m", "t2a", "t3m", "t3a",
                                      "tlm", "tla", "oreb", "dreb", "treb", "ast", "stl", "tov")}})
        d["games"] += 1
        d["sec"] += st.seconds
        for k in ("pts", "val", "t2m", "t2a", "t3m", "t3a", "tlm", "tla",
                  "oreb", "dreb", "treb", "ast", "stl", "tov"):
            d[k] += getattr(st, k)
        d["pm"] += st.plus_minus
        for k in tt:
            tt[k] += getattr(st, k)
        tg.add(st.match_id)
    team_g = len(tg) or 1
    usg_den = tt["t2a"] + tt["t3a"] + 0.44 * tt["tla"] + tt["tov"]
    out = []
    for d in by.values():
        g = d["games"] or 1
        fga = d["t2a"] + d["t3a"]
        fgm = d["t2m"] + d["t3m"]
        mins = d["sec"] / 60
        ts_den = 2 * (fga + 0.44 * d["tla"])
        usg = (100 * (fga + 0.44 * d["tla"] + d["tov"]) * (team_g * 40) / (mins * usg_den)
               if mins and usg_den else 0)
        out.append({
            "player_id": d["player_id"], "name": d["name"], "feb_code": d["feb_code"],
            "games": d["games"], "min": mins / g,
            "pts": d["pts"] / g, "val": d["val"] / g, "pm": d["pm"] / g,
            "reb": d["treb"] / g, "oreb": d["oreb"] / g, "dreb": d["dreb"] / g,
            "ast": d["ast"] / g, "stl": d["stl"] / g, "tov": d["tov"] / g,
            "t3m": d["t3m"] / g, "t3a": d["t3a"] / g, "tlm": d["tlm"] / g, "tla": d["tla"] / g,
            "fg2": _pct(d["t2m"], d["t2a"]), "fg3": _pct(d["t3m"], d["t3a"]),
            "ft": _pct(d["tlm"], d["tla"]), "tc": _pct(fgm, fga),
            "ts": round(d["pts"] / ts_den * 100, 1) if ts_den else 0.0,
            "usg": round(usg, 1), "per": round(d["val"] / mins, 2) if mins else 0.0,
        })
    out.sort(key=lambda x: x["pts"], reverse=True)
    return out


# ============================ tarjetas ============================
def _rank_colors(rank, total):
    if not rank or not total:
        return Y_BG, Y_BD
    if rank <= total / 3:
        return G_BG, G_BD
    if rank <= 2 * total / 3:
        return Y_BG, Y_BD
    return R_BG, R_BD


def _stat_card(value, l1, l2="", rank=None, total=None, plain=False, h=76):
    if plain:
        bg, bd, rl = colors.HexColor("#EEF2F8"), colors.HexColor("#C2CBDA"), ""
    else:
        bg, bd = _rank_colors(rank, total)
        rl = _p(f"{rank}º de {total}", 7, MUTED, align=TA_CENTER) if rank else ""
    rows = [[_p(value, 21, INK, bold=True, align=TA_CENTER)],
            [_p(l1.upper(), 7.5, INK, bold=True, align=TA_CENTER, leading=9)]]
    heights = [26, 11]
    if l2:
        rows.append([_p(l2.upper(), 7.5, INK, bold=True, align=TA_CENTER, leading=9)])
        heights.append(10)
    if rl:
        rows.append([rl])
        heights.append(11)
    t = Table(rows, rowHeights=heights)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 1.3, bd),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _row_of(cards, gap=6 * mm):
    n = len(cards)
    cw = (CONTENT_W - gap * (n - 1)) / n
    cells, widths = [], []
    for i, c in enumerate(cards):
        cells.append(c); widths.append(cw)
        if i < n - 1:
            cells.append(""); widths.append(gap)
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


# ============================ documento ============================
def build_scouting_pdf(session: Session, team_id: int) -> io.BytesIO:
    rep = scouting_mod.report(session, team_id)
    if not rep:
        raise ValueError("Equipo no encontrado")
    team, rec = rep["team"], rep["record"]
    detail = rep["detail_ready"]

    metrics, gsize = ({}, 0)
    me = None
    if detail:
        metrics, gsize = group_metrics(session, team)
        me = metrics.get(team_id)
        if me:
            for k in _KEYS:
                me[f"_rank_{k}"] = _rank_of(metrics, team_id, k)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=landscape(A4), topMargin=12 * mm, bottomMargin=13 * mm,
                          leftMargin=MARGIN, rightMargin=MARGIN, title=f"Scouting {team['name']}")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_footer)])
    S: list = []

    _cover(S, team, rec)
    _last_games(S, session, team_id)
    if detail and me:
        _team_basic(S, me, gsize)
        _comparativa(S, metrics, team_id, me, gsize)
        _team_advanced(S, me, gsize)
        _quadrant_page(S, metrics, team_id)

    min_games = max(3, round(rec["games"] * 0.2))  # descarta muestras marginales (1-3 partidos)
    roster = [p for p in rich_roster(session, team_id) if p["games"] >= min_games] if detail else []
    if roster:
        _player_cards(S, roster)
        _comments_page(S, roster)
        _highlights(S, roster)
        _player_rankings(S, roster)
    if detail and me:
        _team_rankings(S, metrics, team_id)

    doc.build(S)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------- portada
def _cover(S, team, rec):
    S.append(Spacer(1, 14 * mm))
    S.append(_page_title(team["name"]))
    S.append(Spacer(1, 5 * mm))
    logo = _logo_flowable(team, w=46)
    sub = f"{team['competition']}   ·   {team.get('grupo') or ''}"
    if team.get("rank"):
        sub += f"   ·   {team['rank']}º de {team['total_teams']}"
    if logo:
        S.append(logo)
    S.append(Spacer(1, 3 * mm))
    S.append(_p(sub, 12, MUTED, align=TA_CENTER))
    S.append(Spacer(1, 12 * mm))
    win = _stat_card(f"{rec['win_pct']}%", "% de", "victoria",
                     rank=team.get("rank"), total=team.get("total_teams"), h=96)
    cards = [
        _stat_card(str(rec["games"]), "Partidos", "jugados", plain=True, h=96),
        _stat_card(f"{rec['wins']}", "Partidos", "ganados", plain=True, h=96),
        win,
    ]
    n = 3
    gap = 10 * mm
    cw = 58 * mm
    cells, widths = [], []
    for i, c in enumerate(cards):
        cells.append(c); widths.append(cw)
        if i < n - 1:
            cells.append(""); widths.append(gap)
    t = Table([cells], colWidths=widths, hAlign="CENTER")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    S.append(t)


# ---------------------------------------------------------------- últimos partidos
def _last_games(S, session, team_id):
    sched = scouting_mod.schedule(session, team_id)
    played = [r for r in sched if r["my_score"] is not None]
    played.sort(key=lambda r: r["date"] or "", reverse=True)
    last = played[:5]
    S.append(PageBreak())
    S.append(Spacer(1, 6 * mm))
    S.append(_page_title("Últimos partidos"))
    S.append(Spacer(1, 8 * mm))
    head = ["Fecha", "Resultado", "Estado", "Oponente", ""]
    data = [[_p(h, 10, colors.white, bold=True, align=TA_CENTER) for h in head]]
    for r in last:
        d = r["date"] or ""
        try:
            d = "/".join(reversed(d.split("-")))
        except Exception:
            pass
        won = r["result"] == "V"
        estado = _p("W" if won else "L", 12, WIN if won else LOSS, bold=True, align=TA_CENTER)
        link = f'<a href="{FEB_BASE}/partido/{r.get("match_id","")}"><font color="#2F6FE0">Ver</font></a>'
        data.append([
            _p(d, 10, align=TA_CENTER),
            _p(f"{r['my_score']}-{r['their_score']}", 10, align=TA_CENTER, bold=True),
            estado,
            _p((r["opponent"] or "").upper(), 10, align=TA_CENTER),
            _p(link, 9, align=TA_CENTER),
        ])
    cw = [40 * mm, 40 * mm, 30 * mm, 130 * mm, 28 * mm]
    t = Table(data, colWidths=cw, hAlign="CENTER")
    ts = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
          ("LINEBELOW", (0, 0), (-1, -1), 0.6, LINE), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
          ("LINEAFTER", (0, 0), (-2, -1), 0.6, LINE)]
    t.setStyle(TableStyle(ts))
    S.append(t)
    S.append(Spacer(1, 6 * mm))
    S.append(_p("Los 5 partidos más recientes del rival, del más nuevo al más antiguo. "
                "Estado: W = victoria · L = derrota.", 8.5, MUTED, align=TA_CENTER))


# ---------------------------------------------------------------- estadísticas básicas
def _team_basic(S, me, gsize):
    S.append(PageBreak())
    S.append(Spacer(1, 4 * mm))
    S.append(_section("Estadísticas ofensivas")); S.append(Spacer(1, 3 * mm))
    S.append(_row_of([
        _mk(me, gsize, "pts", "Puntos", "por partido"),
        _mk(me, gsize, "ast", "Asistencias", "por partido"),
        _mk(me, gsize, "t3m", "Triples", "anotados"),
        _mk(me, gsize, "t3a", "Triples", "intentados"),
    ]))
    S.append(Spacer(1, 7 * mm))
    S.append(_section("Estadísticas defensivas")); S.append(Spacer(1, 3 * mm))
    S.append(_row_of([
        _mk(me, gsize, "treb", "Rebotes", "totales"),
        _mk(me, gsize, "oreb", "Rebotes", "ofensivos"),
        _mk(me, gsize, "dreb", "Rebotes", "defensivos"),
        _mk(me, gsize, "stl", "Robos", "por partido"),
    ]))
    S.append(Spacer(1, 7 * mm))
    S.append(_section("Porcentajes de acierto")); S.append(Spacer(1, 3 * mm))
    S.append(_row_of([
        _mk(me, gsize, "tc", "% Tiros", "de campo", pct=True),
        _mk(me, gsize, "fg2", "% Tiros", "de 2", pct=True),
        _mk(me, gsize, "fg3", "% Tiros", "de 3", pct=True),
        _mk(me, gsize, "ft", "% Tiros", "libres", pct=True),
    ]))


def _mk(me, gsize, key, l1, l2, pct=False, dec=1, ratio=False):
    val = me[key]
    if pct:
        s = f"{val:.1f}%"
    elif ratio:
        s = f"{val:.2f}"
    else:
        s = f"{val:.{dec}f}"
    return _stat_card(s, l1, l2, rank=me.get(f"_rank_{key}"), total=gsize)


# ---------------------------------------------------------------- comparativa
def _comparativa(S, metrics, team_id, me, gsize):
    S.append(PageBreak())
    S.append(Spacer(1, 3 * mm))
    S.append(_page_title("Comparativa"))
    S.append(Spacer(1, 6 * mm))
    cols = [
        _rank_table("Offensive rating", metrics, team_id, "off_rtg", "{:.1f}"),
        _rank_table("Defensive rating", metrics, team_id, "def_rtg", "{:.1f}"),
        _rank_table("Ritmo", metrics, team_id, "pace", "{:.1f}"),
    ]
    boxes = Table([
        [_stat_card(f"{me['off_rtg']:.1f}", "Offensive", "rating",
                    rank=_rank_of(metrics, team_id, "off_rtg"), total=gsize, h=70)],
        [Spacer(1, 4 * mm)],
        [_stat_card(f"{me['def_rtg']:.1f}", "Defensive", "rating",
                    rank=_rank_of(metrics, team_id, "def_rtg"), total=gsize, h=70)],
        [Spacer(1, 4 * mm)],
        [_stat_card(f"{me['pace']:.1f}", "Ritmo", "posesiones",
                    rank=_rank_of(metrics, team_id, "pace"), total=gsize, h=70)],
    ], colWidths=[42 * mm])
    boxes.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    layout = Table([cols + [boxes]],
                   colWidths=[68 * mm, 68 * mm, 68 * mm, 45 * mm])
    layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    S.append(layout)
    S.append(Spacer(1, 4 * mm))
    S.append(_p("Offensive/Defensive Rating: puntos por 100 posesiones · Ritmo: posesiones por partido.",
                8, MUTED, align=TA_CENTER))


def _rank_table(title, metrics, team_id, key, fmt):
    order = _rank_list(metrics, key)
    t = Table([[_p(f"■ {title.upper()}", 9.5, colors.white, bold=True, align=TA_CENTER)]]
              + [[_rank_row(i, m, key, fmt, m["team_id"] == team_id)]
                 for i, m in enumerate(order, 1)], colWidths=[64 * mm])
    st = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
          ("TOPPADDING", (0, 1), (-1, -1), 0), ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
          ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
          ("BOX", (0, 0), (-1, -1), 0.6, LINE)]
    for i, m in enumerate(order, 1):
        if m["team_id"] == team_id:
            st.append(("BACKGROUND", (0, i), (-1, i), HL_BG))
    t.setStyle(TableStyle(st))
    return t


def _rank_row(i, m, key, fmt, hl):
    inner = Table([[_p(f"{i}. {m['name']}", 8.3, INK, bold=hl),
                    _p(fmt.format(m[key]), 8.3, INK, bold=True, align=TA_RIGHT)]],
                  colWidths=[46 * mm, 18 * mm])
    inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (0, 0), 7), ("RIGHTPADDING", (-1, 0), (-1, 0), 7),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE_SOFT)]))
    return inner


# ---------------------------------------------------------------- métricas avanzadas
def _team_advanced(S, me, gsize):
    def c(key, l1, l2, kind=""):
        val = me[key]
        if kind == "pct":
            s = f"{val:.1f}%"
        elif kind == "r2":
            s = f"{val:.2f}"
        else:
            s = f"{val:.1f}"
        return _stat_card(s, l1, l2, rank=me[f"_rank_{key}"], total=gsize)

    S.append(PageBreak())
    S.append(Spacer(1, 4 * mm))
    S.append(_section("Eficiencia ofensiva (avanzada)")); S.append(Spacer(1, 3 * mm))
    S.append(_row_of([c("efg", "eFG%", "Tiro efectivo", "pct"), c("ts", "TS%", "Eficiencia total", "pct"),
                      c("three_par", "3PAr", "Volumen de 3", "r2"), c("ftr", "FTr", "Agresividad", "r2")]))
    S.append(Spacer(1, 7 * mm))
    S.append(_section("Control y rebote (avanzado)")); S.append(Spacer(1, 3 * mm))
    S.append(_row_of([c("tov_pct", "TOV%", "Pérdidas/posesión", "pct"), c("ast_to", "AST/TO", "Fluidez ofensiva", "r2"),
                      c("orb_pct", "ORB%", "2ª oportunidades", "pct"), c("drb_pct", "DRB%", "Cerrar el aro", "pct")]))
    S.append(Spacer(1, 7 * mm))
    S.append(_section("Efectividad global (avanzada)")); S.append(Spacer(1, 3 * mm))
    net = me["net"]
    S.append(_row_of([c("ppp", "PPP", "Puntos/posesión", "r2"),
                      _stat_card(f"{'+' if net >= 0 else ''}{net:.1f}", "NET RATING", "Ataque − defensa",
                                 rank=me["_rank_net"], total=gsize),
                      c("ast_pct", "AST%", "Colectividad", "pct"),
                      c("ft_eff", "FT EFF", "Puntos de TL", "r2")]))


# ---------------------------------------------------------------- posicionamiento
def _quadrant_page(S, metrics, team_id):
    S.append(PageBreak())
    S.append(Spacer(1, 2 * mm))
    S.append(_page_title("Posicionamiento competitivo"))
    S.append(Spacer(1, 3 * mm))
    img = render_quadrant(metrics, team_id)
    S.append(RLImage(img, width=232 * mm, height=118 * mm, hAlign="CENTER"))
    S.append(Spacer(1, 2 * mm))
    S.append(_p("Rendimiento ofensivo (vertical) frente a defensivo (horizontal, mejor a la derecha). "
                "Las líneas marcan la media del grupo.", 8.5, MUTED, align=TA_CENTER))


def render_quadrant(metrics: dict, team_id: int) -> io.BytesIO:
    W, H = 1760, 900
    pad = 70
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    vals = list(metrics.values())
    xs = [m["def_rtg"] for m in vals]
    ys = [m["off_rtg"] for m in vals]
    xmin, xmax = min(xs) - 2, max(xs) + 2
    ymin, ymax = min(ys) - 2, max(ys) + 2
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)

    def PX(v):  # def_rtg invertido: menor (mejor) a la derecha
        return pad + (xmax - v) / (xmax - xmin) * (W - 2 * pad)

    def PY(v):
        return H - pad - (v - ymin) / (ymax - ymin) * (H - 2 * pad)

    cx, cy = PX(mx), PY(my)
    d.rectangle([cx, pad, W - pad, cy], fill="#E4F5E9")       # élite
    d.rectangle([pad, pad, cx, cy], fill="#FFF3D6")           # ofensivo
    d.rectangle([pad, cy, cx, H - pad], fill="#FBE3E0")       # a mejorar
    d.rectangle([cx, cy, W - pad, H - pad], fill="#E7EEFB")   # defensivo
    d.rectangle([pad, pad, W - pad, H - pad], outline="#C7CFDB", width=2)
    d.line([cx, pad, cx, H - pad], fill="#9AA6B6", width=2)
    d.line([pad, cy, W - pad, cy], fill="#9AA6B6", width=2)
    for txt, x, y, col in [("ÉLITE", W - pad - 140, pad + 12, "#2C8A4A"),
                           ("OFENSIVO", pad + 14, pad + 12, "#B5851F"),
                           ("A MEJORAR", pad + 14, H - pad - 30, "#B23A32"),
                           ("DEFENSIVO", W - pad - 170, H - pad - 30, "#2F6FE0")]:
        d.text((x, y), txt, fill=col)
    for m in vals:
        px, py = PX(m["def_rtg"]), PY(m["off_rtg"])
        pil = _logo_pil(m)
        me = m["team_id"] == team_id
        if pil:
            size = 78 if me else 58
            lg = pil.convert("RGBA")
            lg.thumbnail((size, size))
            if me:
                d.rectangle([px - size / 2 - 4, py - size / 2 - 4, px + size / 2 + 4, py + size / 2 + 4],
                            outline="#E03A2F", width=3)
            img.paste(lg, (int(px - lg.width / 2), int(py - lg.height / 2)), lg)
        else:
            r = 12 if me else 8
            col = (224, 58, 47) if me else (70, 95, 135)
            d.ellipse([px - r, py - r, px + r, py + r], fill=col, outline=(255, 255, 255), width=2)
            d.text((px + r + 3, py - 6), m["name"][:16], fill=(40, 50, 70))
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return buf


# ---------------------------------------------------------------- fichas individuales
def _player_cards(S, roster):
    per_page = 9
    pages = [roster[i:i + per_page] for i in range(0, len(roster), per_page)]
    for pi, chunk in enumerate(pages):
        S.append(PageBreak())
        S.append(Spacer(1, 3 * mm))
        S.append(_page_title("Estadísticas individuales" + (" (cont.)" if pi else "")))
        S.append(Spacer(1, 5 * mm))
        cards = [_player_card(p) for p in chunk]
        while len(cards) % 3:
            cards.append("")
        rows = [cards[i:i + 3] for i in range(0, len(cards), 3)]
        cw = CONTENT_W / 3
        t = Table(rows, colWidths=[cw] * 3)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
        S.append(t)


def _player_card(p):
    W = 88 * mm
    header = Table([[_p(p["name"].upper(), 8.5, colors.white, bold=True, align=TA_CENTER)]], colWidths=[W])
    header.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    photo = _photo_flowable(p["feb_code"], 17, 21)
    pcell = Table([[photo], [_p(f"{p['games']} partidos", 6.5, MUTED, align=TA_CENTER)]],
                  colWidths=[19 * mm])
    pcell.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                               ("ALIGN", (0, 0), (-1, -1), "CENTER")]))

    def band(labels, vals):
        r1 = [_p(l, 6.3, MUTED, bold=True, align=TA_CENTER) for l in labels]
        r2 = [_p(v, 8.6, BLUE, bold=True, align=TA_CENTER) for v in vals]
        t = Table([r1, r2], colWidths=[13.4 * mm] * len(labels))
        t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F5F9")),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.3, LINE_SOFT)]))
        return t

    b1 = band(["MIN", "PTS", "AST", "REB", "VAL"],
              [f"{p['min']:.1f}", f"{p['pts']:.1f}", f"{p['ast']:.1f}", f"{p['reb']:.1f}", f"{p['val']:.1f}"])
    b2 = band(["TC%", "2P%", "3P%", "TL%", "ROB"],
              [f"{p['tc']:.0f}", f"{p['fg2']:.0f}", f"{p['fg3']:.0f}", f"{p['ft']:.0f}", f"{p['stl']:.1f}"])
    b3 = band(["OREB", "DREB", "T3I", "PER", "USG%"],
              [f"{p['oreb']:.1f}", f"{p['dreb']:.1f}", f"{p['t3a']:.1f}", f"{p['per']:.1f}", f"{p['usg']:.0f}"])
    stats = Table([[b1], [b2], [b3]], colWidths=[67 * mm])
    stats.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    body = Table([[pcell, stats]], colWidths=[20 * mm, 68 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    card = Table([[header], [body]], colWidths=[W])
    card.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, NAVY_D),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return card


# ---------------------------------------------------------------- comentarios
def _comments_page(S, roster):
    S.append(PageBreak())
    S.append(Spacer(1, 3 * mm))
    S.append(_page_title("Comentarios jugadores"))
    S.append(Spacer(1, 6 * mm))
    cells = []
    for p in roster:
        header = Table([[_p(p["name"].upper(), 8.5, colors.white, bold=True, align=TA_CENTER)]],
                       colWidths=[128 * mm])
        header.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        photo = _photo_flowable(p["feb_code"], 15, 19)
        body = Table([[photo, ""]], colWidths=[20 * mm, 108 * mm], rowHeights=[24 * mm])
        body.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.7, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("ALIGN", (0, 0), (0, 0), "CENTER"), ("LINEAFTER", (0, 0), (0, 0), 0.7, LINE)]))
        cells.append(Table([[header], [body]], colWidths=[128 * mm]))
    while len(cells) % 2:
        cells.append("")
    rows = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    t = Table(rows, colWidths=[132 * mm, 132 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    # 8 fichas por página como máximo
    if len(rows) > 4:
        # dividir en páginas de 4 filas
        for pi in range(0, len(rows), 4):
            if pi:
                S.append(PageBreak()); S.append(Spacer(1, 3 * mm))
                S.append(_page_title("Comentarios jugadores (cont.)")); S.append(Spacer(1, 6 * mm))
            sub = Table(rows[pi:pi + 4], colWidths=[132 * mm, 132 * mm])
            sub.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                     ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            S.append(sub)
    else:
        S.append(t)


# ---------------------------------------------------------------- jugadores destacados
def _highlights(S, roster):
    top = sorted(roster, key=lambda p: p["val"], reverse=True)[:3]
    if not top:
        return
    S.append(PageBreak())
    S.append(Spacer(1, 3 * mm))
    S.append(_page_title("Jugadores destacados"))
    S.append(Spacer(1, 6 * mm))
    cols = [_highlight_col(p) for p in top]
    cw = CONTENT_W / 3
    t = Table([cols], colWidths=[cw] * 3)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFCFE")),
                           ("BOX", (0, 0), (-1, -1), 0.6, LINE_SOFT),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.6, LINE_SOFT),
                           ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    S.append(t)


def _highlight_col(p):
    strengths, weaks = _profile(p)
    parts = [_p(p["name"].upper(), 15, NAVY, bold=True, align=TA_CENTER), Spacer(1, 3 * mm)]
    intro = (f"Promedia <b>{p['pts']:.1f} PTS</b> y <b>{p['val']:.1f} VAL</b> en "
             f"<b>{p['min']:.1f} min</b>, con un <b>TS% de {p['ts']:.1f}</b>.")
    parts.append(_p(intro, 9, INK, leading=13)); parts.append(Spacer(1, 4 * mm))
    parts.append(_p("FORTALEZAS", 10, WIN, bold=True)); parts.append(Spacer(1, 2 * mm))
    for s in strengths:
        parts.append(_p(f"• {s}", 8.6, INK, leading=12)); parts.append(Spacer(1, 1.6 * mm))
    parts.append(Spacer(1, 3 * mm))
    parts.append(_p("A VIGILAR", 10, LOSS, bold=True)); parts.append(Spacer(1, 2 * mm))
    for w in weaks:
        parts.append(_p(f"• {w}", 8.6, INK, leading=12)); parts.append(Spacer(1, 1.6 * mm))
    return parts


def _profile(p):
    """Fortalezas y debilidades derivadas de los datos (sin texto genérico)."""
    s, w = [], []
    if p["pts"] >= 12:
        s.append(f"Anotador principal con {p['pts']:.1f} puntos por partido.")
    if p["ts"] >= 56:
        s.append(f"Muy eficiente: TS% de {p['ts']:.1f}.")
    if p["fg3"] >= 35 and p["t3a"] >= 3:
        s.append(f"Amenaza exterior fiable ({p['fg3']:.0f}% en {p['t3a']:.1f} triples/partido).")
    if p["reb"] >= 6:
        s.append(f"Domina el rebote con {p['reb']:.1f} por partido.")
    if p["ast"] >= 3:
        s.append(f"Genera juego: {p['ast']:.1f} asistencias por partido.")
    if p["stl"] >= 1.2:
        s.append(f"Activo en defensa con {p['stl']:.1f} robos por partido.")
    if p["ft"] >= 78 and p["tla"] >= 2:
        s.append(f"Fiable desde el tiro libre ({p['ft']:.0f}%).")
    if p["oreb"] >= 2:
        s.append(f"Aporta segundas oportunidades ({p['oreb']:.1f} rebotes ofensivos).")

    if p["tov"] >= 2:
        w.append(f"Pierde {p['tov']:.1f} balones por partido.")
    if p["fg3"] < 30 and p["t3a"] >= 2:
        w.append(f"Poco acierto exterior ({p['fg3']:.0f}% de 3).")
    if p["ft"] < 65 and p["tla"] >= 2:
        w.append(f"Mejorable desde el tiro libre ({p['ft']:.0f}%).")
    if p["ast"] < 1:
        w.append(f"Aporta poco en creación ({p['ast']:.1f} asistencias).")
    if p["reb"] < 3:
        w.append(f"Escaso en el rebote ({p['reb']:.1f} por partido).")
    if p["tc"] < 42 and p["pts"] >= 6:
        w.append(f"Bajo porcentaje de campo ({p['tc']:.0f}%).")
    if p["stl"] < 0.6:
        w.append(f"Poca presión al balón ({p['stl']:.1f} robos).")
    if not s:
        s.append("Rol secundario dentro de la rotación.")
    if not w:
        w.append("Sin debilidades marcadas en los datos.")
    return s[:4], w[:4]


# ---------------------------------------------------------------- rankings jugadores
def _player_rankings(S, roster):
    cats = [
        ("Anotación", "pts", "{:.1f}"), ("Valoración", "val", "{:.1f}"),
        ("Rebotes", "reb", "{:.1f}"), ("Triples/partido", "t3m", "{:.1f}"),
        ("Protagonismo (USG%)", "usg", "{:.1f}%"), ("Robos", "stl", "{:.1f}"),
        ("Asistencias", "ast", "{:.1f}"), ("Tiros libres (%)", "ft", "{:.1f}%"),
        ("Eficiencia tiro (TS%)", "ts", "{:.1f}%"),
    ]
    for pi in range(0, len(cats), 3):
        S.append(PageBreak())
        S.append(Spacer(1, 3 * mm))
        S.append(_page_title("Rankings de jugadores"))
        S.append(Spacer(1, 1 * mm))
        S.append(_p("Promedios por partido de la temporada", 8.5, MUTED, align=TA_CENTER))
        S.append(Spacer(1, 5 * mm))
        cols = [_player_rank_col(l, k, f, roster) for (l, k, f) in cats[pi:pi + 3]]
        cw = CONTENT_W / 3
        t = Table([cols], colWidths=[cw] * 3)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
        S.append(t)


def _player_rank_col(label, key, fmt, roster):
    order = sorted(roster, key=lambda p: p[key], reverse=True)[:8]
    header = _p(f"■ {label.upper()}", 9.5, colors.white, bold=True, align=TA_CENTER)
    rows = [[header]]
    body_rows = []
    for i, p in enumerate(order, 1):
        photo = _photo_flowable(p["feb_code"], 9, 11)
        line = Table([[_p(f"{i}º", 8.5, MUTED, bold=True), photo,
                       _p(p["name"].split(",")[0].strip().upper() if "," in p["name"] else p["name"].upper(),
                          8.2, INK, bold=True),
                       _p(fmt.format(p[key]), 9, INK, bold=True, align=TA_RIGHT)]],
                     colWidths=[8 * mm, 12 * mm, 40 * mm, 20 * mm])
        line.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("LEFTPADDING", (0, 0), (0, 0), 4), ("RIGHTPADDING", (-1, 0), (-1, 0), 6),
                                  ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                  ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE_SOFT)]))
        body_rows.append([line])
    t = Table(rows + body_rows, colWidths=[80 * mm])
    st = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
          ("TOPPADDING", (0, 1), (-1, -1), 0), ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
          ("LEFTPADDING", (0, 1), (-1, -1), 0), ("RIGHTPADDING", (0, 1), (-1, -1), 0),
          ("BOX", (0, 0), (-1, -1), 0.6, LINE)]
    t.setStyle(TableStyle(st))
    return t


# ---------------------------------------------------------------- rankings equipos
def _team_rankings(S, metrics, team_id):
    cats = [
        ("Anotación", "pts", "{:.1f}"), ("Rebotes", "treb", "{:.1f}"),
        ("Asistencias", "ast", "{:.1f}"), ("Pérdidas", "tov", "{:.1f}"),
        ("eFG% (tiro efectivo)", "efg", "{:.1f}%"), ("Robos", "stl", "{:.1f}"),
        ("% Tiros de campo", "tc", "{:.1f}%"), ("FTr (agresividad)", "ftr", "{:.2f}"),
        ("% Tiros libres", "ft", "{:.1f}%"), ("% Triples", "fg3", "{:.1f}%"),
        ("% Tiros de 2", "fg2", "{:.1f}%"), ("Puntos recibidos", "pts_against", "{:.1f}"),
    ]
    for pi in range(0, len(cats), 4):
        S.append(PageBreak())
        S.append(Spacer(1, 3 * mm))
        S.append(_page_title("Rankings de equipos"))
        S.append(Spacer(1, 1 * mm))
        S.append(_p("Promedios por partido dentro del grupo", 8.5, MUTED, align=TA_CENTER))
        S.append(Spacer(1, 5 * mm))
        cols = [_team_rank_col(l, k, f, metrics, team_id) for (l, k, f) in cats[pi:pi + 4]]
        cw = CONTENT_W / 4
        t = Table([cols], colWidths=[cw] * 4)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
        S.append(t)


def _team_rank_col(label, key, fmt, metrics, team_id):
    order = _rank_list(metrics, key)
    rows = [[_p(f"■ {label.upper()}", 8.5, colors.white, bold=True, align=TA_CENTER)]]
    for i, m in enumerate(order, 1):
        rows.append([_team_rank_row(i, m, key, fmt, m["team_id"] == team_id)])
    t = Table(rows, colWidths=[62 * mm])
    st = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
          ("TOPPADDING", (0, 1), (-1, -1), 0), ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
          ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
          ("BOX", (0, 0), (-1, -1), 0.6, LINE)]
    for i, m in enumerate(order, 1):
        if m["team_id"] == team_id:
            st.append(("BACKGROUND", (0, i), (-1, i), HL_BG))
    t.setStyle(TableStyle(st))
    return t


def _team_rank_row(i, m, key, fmt, hl):
    name = m["name"]
    if len(name) > 22:
        name = name[:21] + "…"
    inner = Table([[_p(f"{i}º {name}", 7.6, INK, bold=hl),
                    _p(fmt.format(m[key]), 7.8, INK, bold=True, align=TA_RIGHT)]],
                  colWidths=[44 * mm, 18 * mm])
    inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (0, 0), 6), ("RIGHTPADDING", (-1, 0), (-1, 0), 6),
                               ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE_SOFT)]))
    return inner


# ---------------------------------------------------------------- pie de página
def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(FAINT)
    canvas.drawCentredString(PW / 2, 7 * mm, "PI SCOUTING")
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(PW - MARGIN, 7 * mm, f"{doc.page}")
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 7 * mm, "Datos FEB · LiveStats")
    canvas.restoreState()
