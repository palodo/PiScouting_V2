"""Informe de scouting en PDF — estilo visual (horizontal, claro, muy informativo).

Inspirado en los informes originales de PI Scouting: portada, perfil del equipo con
tarjetas coloreadas por ranking dentro del grupo, posicionamiento competitivo,
estadísticas individuales con foto y mapas de tiro sobre la pista de madera.
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
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image as RLImage,
)
from sqlmodel import Session, select

from .config import DATA_DIR, COURT_IMAGE
from .models import Team, PlayerMatchStat
from . import scouting as scouting_mod, shots as shots_mod, analytics

# ---- Paleta (clara, profesional) ----
NAVY = colors.HexColor("#1E3A5F")
INK = colors.HexColor("#2A3340")
MUTED = colors.HexColor("#6B7688")
ACCENT = colors.HexColor("#FF5A1F")
G_BG, G_BD = colors.HexColor("#E7F6EC"), colors.HexColor("#2FA45B")
Y_BG, Y_BD = colors.HexColor("#FFF6E0"), colors.HexColor("#E0A526")
R_BG, R_BD = colors.HexColor("#FCE9E7"), colors.HexColor("#D8453C")
LINE = colors.HexColor("#DCE1EA")
ZEBRA = colors.HexColor("#F5F7FA")

PW, PH = landscape(A4)
CONTENT_W = PW - 30 * mm

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


def _title(text):
    return _p(text, 26, NAVY, bold=True, align=TA_CENTER)


# ============================ imágenes ============================
def _fetch_image(url: Optional[str], cache_path) -> Optional[Image.Image]:
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


def team_logo_img(team) -> Optional[RLImage]:
    img = _fetch_image(team.get("logo") if isinstance(team, dict) else team.logo,
                       LOGO_CACHE / f"{(team.get('team_id') if isinstance(team, dict) else team.id)}.img")
    if not img:
        return None
    bg = Image.new("RGBA", img.size, (255, 255, 255, 0))
    bg.paste(img, (0, 0), img.convert("RGBA"))
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def player_photo(feb_code: Optional[str]) -> Optional[io.BytesIO]:
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


# ---- mapa de tiro sobre la pista de madera (mitad derecha) ----
_COURT = None


def _court_half() -> Image.Image:
    global _COURT
    if _COURT is None:
        full = Image.open(COURT_IMAGE).convert("RGB")
        W, H = full.size
        _COURT = full.crop((W // 2, 0, W, H))  # mitad derecha (canasta a la derecha)
    return _COURT.copy()


def render_shotchart(shots: list[dict]) -> io.BytesIO:
    court = _court_half()
    W, H = court.size
    d = ImageDraw.Draw(court, "RGBA")
    for s in shots:
        px = s["hx"] / 100 * W
        py = s["hy"] / 100 * H
        r = max(4, W // 90)
        if s["made"]:
            d.ellipse([px - r, py - r, px + r, py + r], fill=(34, 197, 94, 235), outline=(255, 255, 255, 255), width=1)
        else:
            d.ellipse([px - r, py - r, px + r, py + r], fill=(239, 68, 68, 210), outline=(120, 0, 0, 255), width=1)
    buf = io.BytesIO()
    court.save(buf, "PNG")
    buf.seek(0)
    return buf


# ---- posicionamiento competitivo (cuadrante) ----
def render_quadrant(standings: list[dict], team_id: int) -> io.BytesIO:
    W, H = 1500, 900
    pad = 90
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    xs = [s["pts_against_avg"] for s in standings]
    ys = [s["pts_for_avg"] for s in standings]
    if not xs:
        buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0); return buf
    # eje X = puntos en contra (invertido: menos = mejor = derecha); eje Y = puntos a favor
    xmin, xmax = min(xs) - 2, max(xs) + 2
    ymin, ymax = min(ys) - 2, max(ys) + 2
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)

    def PX(v):  # invertido
        return pad + (xmax - v) / (xmax - xmin) * (W - 2 * pad)

    def PY(v):
        return H - pad - (v - ymin) / (ymax - ymin) * (H - 2 * pad)

    cx, cy = PX(mx), PY(my)
    # cuadrantes de fondo
    d.rectangle([cx, pad, W - pad, cy], fill="#E7F6EC")   # arriba-dcha: élite
    d.rectangle([pad, pad, cx, cy], fill="#FFF7E6")       # arriba-izq: ofensivo
    d.rectangle([pad, cy, cx, H - pad], fill="#FCEAE8")   # abajo-izq: necesita mejorar
    d.rectangle([cx, cy, W - pad, H - pad], fill="#EAF2FB")  # abajo-dcha: defensivo
    d.rectangle([pad, pad, W - pad, H - pad], outline="#C7CFDB", width=2)
    d.line([cx, pad, cx, H - pad], fill="#9AA6B6", width=2)
    d.line([pad, cy, W - pad, cy], fill="#9AA6B6", width=2)
    labels = [("ÉLITE", W - pad - 150, pad + 16, "#2FA45B"), ("OFENSIVO", pad + 16, pad + 16, "#E0A526"),
              ("A MEJORAR", pad + 16, H - pad - 34, "#D8453C"), ("DEFENSIVO", W - pad - 170, H - pad - 34, "#3A7BD5")]
    for txt, lx, ly, col in labels:
        d.text((lx, ly), txt, fill=col)
    # puntos
    for s in standings:
        px, py = PX(s["pts_against_avg"]), PY(s["pts_for_avg"])
        me = s["team_id"] == team_id
        rr = 13 if me else 8
        col = (255, 90, 31) if me else (60, 90, 130)
        d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=col, outline=(255, 255, 255), width=2)
        name = s["name"][:16]
        d.text((px + rr + 3, py - 6), name, fill=(30, 40, 60) if me else (90, 100, 115))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================ tarjetas ============================
def _rank_style(rank: int, total: int):
    if not rank or total <= 1:
        return Y_BG, Y_BD
    third = total / 3
    if rank <= third:
        return G_BG, G_BD
    if rank <= 2 * third:
        return Y_BG, Y_BD
    return R_BG, R_BD


def _stat_card(value: str, label: str, rank: Optional[int] = None, total: Optional[int] = None,
               plain=False):
    if plain:
        bg, bd = colors.HexColor("#EEF2F7"), colors.HexColor("#B9C4D4")
        rank_row = ""
    else:
        bg, bd = _rank_style(rank or 0, total or 0)
        rank_row = _p(f"{rank}º de {total}", 7, MUTED, align=TA_CENTER) if rank else ""
    rows = [[_p(value, 20, INK, bold=True, align=TA_CENTER)],
            [_p(label.upper(), 7.5, INK, bold=True, align=TA_CENTER, leading=9)]]
    if rank_row:
        rows.append([rank_row])
    t = Table(rows, rowHeights=[24, 16] + ([11] if rank_row else []))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 1.4, bd),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def _card_row(cards, gap=6 * mm):
    n = len(cards)
    cw = (CONTENT_W - gap * (n - 1)) / n
    cells, widths = [], []
    for i, c in enumerate(cards):
        cells.append(c)
        widths.append(cw)
        if i < n - 1:
            cells.append("")
            widths.append(gap)
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def _section_title(text):
    return _p(text.upper(), 13, NAVY, bold=True, align=TA_CENTER)


# ============================ ranks del grupo ============================
def _group_stats(session: Session, team) -> dict:
    """Para el equipo objetivo, devuelve {clave: (valor, rank, total)} dentro de su grupo."""
    q = select(Team).where(Team.competition == team["competition"], Team.season == team["season"])
    if team.get("grupo"):
        q = q.where(Team.grupo == team["grupo"])
    group = session.exec(q).all()

    def per_game(t):
        rec = analytics.team_record(session, t.id)
        sh = analytics.team_shooting(session, t.id)
        g = rec["games"] or 1
        tot = sh["totals"]
        fga = tot["t2a"] + tot["t3a"]
        fgm = tot["t2m"] + tot["t3m"]
        return {
            "pts": rec["pts_for_avg"], "pts_against": rec["pts_against_avg"],
            "ast": round(tot["ast"] / g, 1), "t3m": round(tot["t3m"] / g, 1),
            "t3a": round(tot["t3a"] / g, 1), "treb": round(tot["treb"] / g, 1),
            "oreb": round(tot["oreb"] / g, 1), "stl": round(tot["stl"] / g, 1),
            "fg2": sh["fg2_pct"], "fg3": sh["fg3_pct"], "ft": sh["ft_pct"],
            "fg": round(100 * fgm / fga, 1) if fga else 0.0,
        }

    vals = {t.id: per_game(t) for t in group}
    lower_better = {"pts_against"}
    keys = ["pts", "pts_against", "ast", "t3m", "t3a", "treb", "oreb", "stl", "fg2", "fg3", "ft", "fg"]
    out = {}
    tid = team["team_id"]
    for k in keys:
        ordered = sorted(vals.items(), key=lambda kv: kv[1][k], reverse=(k not in lower_better))
        rank = next((i + 1 for i, (t_id, _) in enumerate(ordered) if t_id == tid), None)
        out[k] = (vals[tid][k], rank, len(group))
    return out


# ============================ documento ============================
def build_scouting_pdf(session: Session, team_id: int) -> io.BytesIO:
    rep = scouting_mod.report(session, team_id)
    if not rep:
        raise ValueError("Equipo no encontrado")
    team, rec, adv, sh = rep["team"], rep["record"], rep["advanced"], rep["shooting"]
    detail = rep["detail_ready"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=12 * mm, bottomMargin=10 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm, title=f"Scouting {team['name']}")
    S: list = []

    # ---------- PORTADA ----------
    S.append(Spacer(1, 18 * mm))
    S.append(_title(team["name"]))
    S.append(Spacer(1, 4 * mm))
    logo = team_logo_img(team)
    if logo:
        S.append(RLImage(logo, width=44 * mm, height=44 * mm, kind="proportional", hAlign="CENTER"))
    rank_txt = f"{team['rank']}º de {team['total_teams']}" if team.get("rank") else "—"
    S.append(Spacer(1, 3 * mm))
    S.append(_p(f"{team['competition']}  ·  {team.get('grupo') or ''}", 12, MUTED, align=TA_CENTER))
    S.append(Spacer(1, 8 * mm))
    S.append(_card_row([
        _stat_card(str(rec["games"]), "Partidos jugados", plain=True),
        _stat_card(f"{rec['wins']}-{rec['losses']}", "Balance V-D", plain=True),
        _stat_card(f"{rec['win_pct']}%", "% de victoria",
                   rank=team.get("rank"), total=team.get("total_teams")),
        _stat_card(f"{'+' if rec['diff_avg'] >= 0 else ''}{rec['diff_avg']}", "Diferencial",
                   rank=team.get("rank"), total=team.get("total_teams")),
    ]))

    # ---------- PERFIL DEL EQUIPO ----------
    if detail:
        gs = _group_stats(session, team)
        S.append(PageBreak())
        S.append(_p("PERFIL DEL EQUIPO", 22, NAVY, bold=True, align=TA_CENTER))
        S.append(Spacer(1, 2 * mm))
        S.append(_p(f"Rendimiento y ranking dentro del grupo ({team.get('total_teams')} equipos)",
                    9, MUTED, align=TA_CENTER))
        S.append(Spacer(1, 6 * mm))

        def card(key, label, fmt="{}"):
            v, r, t = gs[key]
            return _stat_card(fmt.format(v), label, rank=r, total=t)

        S.append(_section_title("Ataque")); S.append(Spacer(1, 3 * mm))
        S.append(_card_row([card("pts", "Puntos / partido"), card("ast", "Asistencias / partido"),
                            card("t3m", "Triples / partido"), card("t3a", "Triples intentados")]))
        S.append(Spacer(1, 5 * mm))
        S.append(_section_title("Defensa y rebote")); S.append(Spacer(1, 3 * mm))
        S.append(_card_row([card("pts_against", "Puntos recibidos"), card("treb", "Rebotes / partido"),
                            card("oreb", "Reb. ofensivos"), card("stl", "Robos / partido")]))
        S.append(Spacer(1, 5 * mm))
        S.append(_section_title("Porcentajes de acierto")); S.append(Spacer(1, 3 * mm))
        S.append(_card_row([card("fg2", "% Tiros de 2", "{}%"), card("fg3", "% Tiros de 3", "{}%"),
                            card("ft", "% Tiros libres", "{}%"), card("fg", "% Tiros de campo", "{}%")]))
        S.append(Spacer(1, 5 * mm))
        S.append(_section_title("Métricas avanzadas")); S.append(Spacer(1, 3 * mm))
        S.append(_card_row([
            _stat_card(str(adv["off_rtg"]), "Rating ofensivo", plain=True),
            _stat_card(str(adv["pace"]), "Ritmo (posesiones)", plain=True),
            _stat_card(f"{adv['ts_pct']}%", "True Shooting", plain=True),
            _stat_card(str(adv["ast_to"]), "Asist. / Pérdida", plain=True),
        ]))

    # ---------- POSICIONAMIENTO + CLASIFICACIÓN ----------
    S.append(PageBreak())
    S.append(_p("POSICIONAMIENTO EN EL GRUPO", 22, NAVY, bold=True, align=TA_CENTER))
    S.append(Spacer(1, 4 * mm))
    quad = RLImage(render_quadrant(rep["standings"], team_id), width=150 * mm, height=90 * mm)
    # tabla clasificación compacta
    head = ["#", "Equipo", "V-D", "PF", "PC", "+/-"]
    data = [[_p(h, 7.5, colors.white, bold=True, align=TA_CENTER if h != "Equipo" else TA_LEFT) for h in head]]
    hl = []
    for i, s in enumerate(rep["standings"], 1):
        me = s["team_id"] == team_id
        if me:
            hl.append(i)
        data.append([
            _p(s["rank"], 7.5, align=TA_CENTER, bold=me), _p(s["name"][:22], 7.5, bold=me),
            _p(f"{s['wins']}-{s['losses']}", 7.5, align=TA_CENTER),
            _p(s["pts_for_avg"], 7.5, align=TA_CENTER), _p(s["pts_against_avg"], 7.5, align=TA_CENTER),
            _p(f"{'+' if s['diff_avg'] >= 0 else ''}{s['diff_avg']}", 7.5,
               G_BD if s["diff_avg"] >= 0 else R_BD, align=TA_CENTER, bold=True),
        ])
    tbl = Table(data, colWidths=[8 * mm, 40 * mm, 15 * mm, 14 * mm, 14 * mm, 15 * mm], repeatRows=1)
    ts = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 2.2),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2), ("LEFTPADDING", (0, 0), (-1, -1), 4)]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    for i in hl:
        ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFE9DF")))
    tbl.setStyle(TableStyle(ts))
    layout = Table([[quad, tbl]], colWidths=[152 * mm, 115 * mm])
    layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    S.append(layout)

    # ---------- ESTADÍSTICAS INDIVIDUALES ----------
    roster = [p for p in rep["roster"] if p["games"] >= 1]
    if detail and roster:
        S.append(PageBreak())
        S.append(_p("ESTADÍSTICAS INDIVIDUALES", 22, NAVY, bold=True, align=TA_CENTER))
        S.append(Spacer(1, 5 * mm))
        cards = [_player_card(p) for p in roster[:9]]
        S.append(_grid(cards, 3))

    # ---------- SHOT CHARTS ----------
    if detail:
        shooters = sorted(roster, key=lambda p: p["ppg"], reverse=True)[:8]
        cards = []
        for p in shooters:
            ps = shots_mod.shots_for_player(session, p["player_id"])
            if not ps:
                continue
            cards.append(_shot_card(p, ps))
        if cards:
            S.append(PageBreak())
            S.append(_p("MAPAS DE TIRO", 22, NAVY, bold=True, align=TA_CENTER))
            S.append(Spacer(1, 5 * mm))
            S.append(_grid(cards, 4))

    S.append(Spacer(1, 6 * mm))
    S.append(_p("PiScouting · datos FEB (LiveStats)", 8, MUTED, align=TA_CENTER))
    doc.build(S)
    buf.seek(0)
    return buf


def _grid(cards, cols):
    while len(cards) % cols:
        cards.append("")
    rows = [cards[i:i + cols] for i in range(0, len(cards), cols)]
    cw = CONTENT_W / cols
    t = Table(rows, colWidths=[cw] * cols)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _player_card(p):
    photo = player_photo(p.get("feb_code"))
    photo_fl = RLImage(photo, width=18 * mm, height=22 * mm) if photo else _p("", 8)
    header = Table([[_p(p["name"], 8.5, colors.white, bold=True)]], colWidths=[80 * mm])
    header.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    labels = ["MIN", "PTS", "REB", "AST", "VAL"]
    vals = [p["min_avg"], p["ppg"], p["rpg"], p["apg"], p["val_avg"]]
    labels2 = ["T2%", "T3%", "TL%", "TS%", "+/-"]
    pm = p["plus_minus_avg"]
    vals2 = [p["fg2_pct"], p["fg3_pct"], p["ft_pct"], p["ts_pct"], f"{'+' if pm >= 0 else ''}{pm}"]

    def statrow(lbls, vls):
        r1 = [_p(l, 6.5, MUTED, bold=True, align=TA_CENTER) for l in lbls]
        r2 = [_p(v, 9, NAVY, bold=True, align=TA_CENTER) for v in vls]
        t = Table([r1, r2], colWidths=[12 * mm] * len(lbls))
        t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.3, LINE)]))
        return t

    stats = Table([[statrow(labels, vals)], [statrow(labels2, vals2)]])
    stats.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    body = Table([[photo_fl, stats]], colWidths=[20 * mm, 62 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
    card = Table([[header], [body]], colWidths=[84 * mm])
    card.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.7, LINE), ("TOPPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return card


def _shot_card(p, shots):
    photo = player_photo(p.get("feb_code"))
    made = sum(1 for s in shots if s["made"])
    header = Table([[_p(p["name"], 7.5, colors.white, bold=True)]], colWidths=[62 * mm])
    header.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
    chart = RLImage(render_shotchart(shots), width=42 * mm, height=42 * mm * 0.54)
    photo_fl = RLImage(photo, width=13 * mm, height=16 * mm) if photo else _p("", 7)
    body = Table([[photo_fl, chart]], colWidths=[15 * mm, 47 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    legend = _p(f"{len(shots)} tiros · {made} anotados · {round(100*made/len(shots))}%", 6.5, MUTED, align=TA_CENTER)
    card = Table([[header], [body], [legend]], colWidths=[64 * mm])
    card.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.7, LINE), ("TOPPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return card
