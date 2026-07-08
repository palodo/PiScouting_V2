"""Generador del informe de scouting en PDF (ReportLab + Pillow).

Produce un informe visual del rival usando todos los datos de la BBDD: perfil y
métricas avanzadas, clasificación del grupo, plantilla con +/- y TS%, jugadores clave
con foto y mapa de tiro, y el mapa de tiro del equipo.
"""
from __future__ import annotations

import io
import math
import os
from typing import Optional

import requests
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, KeepTogether,
)
from sqlmodel import Session

from .config import DATA_DIR
from . import scouting as scouting_mod, shots as shots_mod

# ---- Paleta (deportivo oscuro premium, adaptada a impresión) ----
INK = colors.HexColor("#12161F")
PANEL = colors.HexColor("#1B2130")
ACCENT = colors.HexColor("#FF6B35")
ACCENT2 = colors.HexColor("#3AA0FF")
MUTED = colors.HexColor("#8A97A8")
LIGHT = colors.HexColor("#F2F4F8")
ZEBRA = colors.HexColor("#F7F8FB")
GREEN = colors.HexColor("#1FA463")
RED = colors.HexColor("#D8453C")
LINE = colors.HexColor("#D9DEE7")

PHOTO_CACHE = DATA_DIR / "player_photos_cache"
PHOTO_CACHE.mkdir(exist_ok=True)


# ============================ Mapa de tiro (Pillow) ============================
def render_shotchart(shots: list[dict], scale: int = 34) -> io.BytesIO:
    """Dibuja una media pista vertical con los tiros (verde=anotado, rojo=fallado).

    Coordenadas de entrada: hx 0(medio campo, arriba)..100(fondo, abajo); hy 0..100 ancho.
    """
    M = scale
    W, H = 15 * M, 14 * M
    pad = 6
    img = Image.new("RGB", (W + pad * 2, H + pad * 2), "#161F2B")
    d = ImageDraw.Draw(img)
    ox, oy = pad, pad
    line = "#5C6E82"

    def X(hy):  # ancho
        return ox + hy / 100 * W

    def Y(hx):  # largo (0 arriba .. 100 abajo)
        return oy + hx / 100 * H

    hoopX = ox + W / 2
    hoopY = oy + H - 1.575 * M
    # pista
    d.rectangle([ox, oy, ox + W, oy + H], outline=line, width=2)
    # zona
    keyW, keyH = 4.9 * M, 5.8 * M
    d.rectangle([hoopX - keyW / 2, oy + H - keyH, hoopX + keyW / 2, oy + H], outline=line, width=2)
    # aro + tablero
    d.line([hoopX - 0.9 * M, oy + H - 1.2 * M, hoopX + 0.9 * M, oy + H - 1.2 * M], fill=line, width=3)
    d.ellipse([hoopX - 0.23 * M, hoopY - 0.23 * M, hoopX + 0.23 * M, hoopY + 0.23 * M], outline=line, width=2)

    def polyline(fn, x0, x1, steps=60):
        pts = []
        for i in range(steps + 1):
            x = x0 + (x1 - x0) * i / steps
            y = fn(x)
            if y is not None:
                pts.append((x, y))
        if len(pts) > 1:
            d.line(pts, fill=line, width=2)

    # semicírculo tiros libres (encima de la línea de tiros libres)
    ftY = oy + H - keyH
    R = 1.8 * M
    polyline(lambda x: ftY - math.sqrt(max(0, R * R - (x - hoopX) ** 2)), hoopX - R, hoopX + R)
    # línea de 3
    R3 = 6.75 * M
    cxl, cxr = ox + 0.9 * M, ox + W - 0.9 * M
    yl = hoopY - math.sqrt(max(0, R3 * R3 - (hoopX - cxl) ** 2))
    d.line([cxl, oy + H, cxl, yl], fill=line, width=2)
    d.line([cxr, oy + H, cxr, yl], fill=line, width=2)
    polyline(lambda x: hoopY - math.sqrt(max(0, R3 * R3 - (x - hoopX) ** 2)), cxl, cxr)
    # semicírculo de medio campo (arriba)
    polyline(lambda x: oy + math.sqrt(max(0, R * R - (x - hoopX) ** 2)), hoopX - R, hoopX + R)

    # tiros
    for s in shots:
        cx, cy = X(s["hy"]), Y(s["hx"])
        r = 5
        if s["made"]:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#2EC26A", outline="#0f5", width=1)
        else:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#E0524B", width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def get_player_photo(feb_code: Optional[str]) -> Optional[io.BytesIO]:
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
                img.save(cached, format="JPEG", quality=88)
                return io.BytesIO(cached.read_bytes())
    except Exception:
        pass
    return None


# ============================ Estilos ReportLab ============================
_styles = getSampleStyleSheet()


def _p(text, size=9, color=colors.HexColor("#2A2F3A"), bold=False, align=TA_LEFT, leading=None):
    return Paragraph(text, ParagraphStyle(
        "x", parent=_styles["Normal"], fontSize=size,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        textColor=color, alignment=align, leading=leading or size + 3,
    ))


def _stat_cards(items: list[tuple[str, str]], cols: int = 6, accent=ACCENT):
    """Fila de tarjetas de estadística (etiqueta arriba, valor grande)."""
    cells = []
    for label, value in items:
        inner = Table([[_p(value, 15, INK, bold=True, align=TA_CENTER)],
                       [_p(label.upper(), 6.5, MUTED, align=TA_CENTER)]],
                      rowHeights=[16, 10])
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("LINEABOVE", (0, 0), (-1, 0), 2, accent),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        cells.append(inner)
    # rellenar hasta múltiplo de cols
    while len(cells) % cols:
        cells.append("")
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    t = Table(rows, colWidths=[(180 * mm) / cols] * cols)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _section(title: str, accent=ACCENT):
    t = Table([[_p(title.upper(), 11, colors.white, bold=True)]], colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("LINEBEFORE", (0, 0), (0, 0), 4, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _logo_flowable(url: Optional[str], size_mm=16):
    if not url:
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if r.status_code == 200 and len(r.content) > 500:
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            bg = Image.new("RGBA", img.size, (255, 255, 255, 0))
            bg.paste(img, (0, 0), img)
            buf = io.BytesIO()
            bg.convert("RGB").save(buf, format="PNG")
            buf.seek(0)
            return RLImage(buf, width=size_mm * mm, height=size_mm * mm, kind="proportional")
    except Exception:
        pass
    return ""


# ============================ Documento ============================
def build_scouting_pdf(session: Session, team_id: int) -> io.BytesIO:
    rep = scouting_mod.report(session, team_id)
    if not rep:
        raise ValueError("Equipo no encontrado")
    team = rep["team"]
    rec = rep["record"]
    adv = rep["advanced"]
    sh = rep["shooting"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=12 * mm, bottomMargin=12 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            title=f"Scouting {team['name']}")
    story: list = []

    # ---- Cabecera/portada ----
    logo = _logo_flowable(team.get("logo"), 18)
    rank_txt = f"{team['rank']}º de {team['total_teams']}" if team.get("rank") else "—"
    head_right = Table([
        [_p("INFORME DE SCOUTING", 8, ACCENT, bold=True)],
        [_p(team["name"], 20, colors.white, bold=True)],
        [_p(f"{team['competition']}  ·  {team.get('grupo') or ''}", 9, MUTED)],
        [_p(f"Clasificación {rank_txt}   ·   Balance {rec['wins']}-{rec['losses']}   ·   "
            f"{rec['pts_for_avg']} PF / {rec['pts_against_avg']} PC", 9, LIGHT)],
    ], colWidths=[150 * mm])
    head_right.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 8),
                                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    header = Table([[logo, head_right]], colWidths=[30 * mm, 150 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 8), ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [header, Spacer(1, 8)]

    # ---- Perfil avanzado ----
    if rep["detail_ready"]:
        story += [_section("Perfil avanzado"), Spacer(1, 5)]
        story.append(_stat_cards([
            ("OffRtg", str(adv["off_rtg"])), ("Ritmo", str(adv["pace"])),
            ("eFG%", f"{adv['efg_pct']}%"), ("TS%", f"{adv['ts_pct']}%"),
            ("AST/TO", str(adv["ast_to"])), ("% Tiros 3", f"{adv['three_rate']}%"),
        ]))
        story.append(Spacer(1, 4))
        story.append(_stat_cards([
            ("T2%", f"{sh['fg2_pct']}%"), ("T3%", f"{sh['fg3_pct']}%"),
            ("TL%", f"{sh['ft_pct']}%"), ("Rebotes", str(sh["reb_total"])),
            ("Asist.", str(sh["assists"])), ("Pérdidas", str(sh["turnovers"])),
        ]))
        story.append(Spacer(1, 10))
    else:
        story += [_p("Análisis avanzado no disponible: falta descargar el detalle de sus partidos "
                     "(botón «Preparar scouting» en la app).", 9, MUTED), Spacer(1, 8)]

    # ---- Clasificación del grupo ----
    story += [_section("Clasificación del grupo"), Spacer(1, 5)]
    head = ["#", "Equipo", "PJ", "V-D", "PF", "PC", "+/-"]
    data = [[_p(h, 7.5, colors.white, bold=True, align=TA_CENTER if h != "Equipo" else TA_LEFT) for h in head]]
    hl_rows = []
    for i, s in enumerate(rep["standings"], 1):
        is_me = s["team_id"] == team_id
        if is_me:
            hl_rows.append(i)
        diff = f"{'+' if s['diff_avg'] >= 0 else ''}{s['diff_avg']}"
        data.append([
            _p(str(s["rank"]), 8, align=TA_CENTER, bold=is_me),
            _p(s["name"], 8, bold=is_me),
            _p(str(s["games"]), 8, align=TA_CENTER),
            _p(f"{s['wins']}-{s['losses']}", 8, align=TA_CENTER, bold=is_me),
            _p(str(s["pts_for_avg"]), 8, align=TA_CENTER),
            _p(str(s["pts_against_avg"]), 8, align=TA_CENTER),
            _p(diff, 8, GREEN if s["diff_avg"] >= 0 else RED, align=TA_CENTER, bold=True),
        ])
    tbl = Table(data, colWidths=[10 * mm, 74 * mm, 14 * mm, 20 * mm, 20 * mm, 20 * mm, 22 * mm], repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            ts.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    for i in hl_rows:
        ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFE9DF")))
        ts.append(("LINEBEFORE", (0, i), (0, i), 3, ACCENT))
    tbl.setStyle(TableStyle(ts))
    story += [tbl, Spacer(1, 10)]

    # ---- Plantilla ----
    if rep["roster"]:
        story += [_section("Plantilla"), Spacer(1, 5)]
        head = ["Jugador", "PJ", "MIN", "PTS", "REB", "AST", "T3/PJ", "TS%", "VAL", "+/-"]
        data = [[_p(h, 7.5, colors.white, bold=True, align=TA_LEFT if h == "Jugador" else TA_CENTER) for h in head]]
        for p in rep["roster"]:
            pm = p["plus_minus_avg"]
            data.append([
                _p(p["name"], 8),
                _p(str(p["games"]), 8, align=TA_CENTER),
                _p(str(p["min_avg"]), 8, align=TA_CENTER),
                _p(str(p["ppg"]), 8, align=TA_CENTER, bold=True),
                _p(str(p["rpg"]), 8, align=TA_CENTER),
                _p(str(p["apg"]), 8, align=TA_CENTER),
                _p(str(p["fg3a_avg"]), 8, align=TA_CENTER),
                _p(str(p["ts_pct"]), 8, align=TA_CENTER),
                _p(str(p["val_avg"]), 8, align=TA_CENTER),
                _p(f"{'+' if pm >= 0 else ''}{pm}", 8, GREEN if pm >= 0 else RED, align=TA_CENTER, bold=True),
            ])
        w = [56 * mm] + [13.7 * mm] * 9
        tbl = Table(data, colWidths=w, repeatRows=1)
        ts = [
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]
        for i in range(1, len(data)):
            if i % 2 == 0:
                ts.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        tbl.setStyle(TableStyle(ts))
        story += [tbl, Spacer(1, 10)]

    # ---- Jugadores clave ----
    if rep["detail_ready"] and rep["key_players"]:
        story += [_section("Jugadores clave"), Spacer(1, 6)]
        cards = []
        for p in rep["key_players"][:4]:
            photo = get_player_photo(p.get("feb_code"))
            photo_fl = RLImage(photo, width=16 * mm, height=16 * mm) if photo else _p("", 8)
            pshots = shots_mod.shots_for_player(session, p["player_id"])
            chart = RLImage(render_shotchart(pshots), width=42 * mm, height=39 * mm) if pshots else _p("Sin tiros", 7, MUTED)
            pm = p["plus_minus_avg"]
            info = Table([
                [photo_fl, _p(p["name"], 9, INK, bold=True)],
            ], colWidths=[18 * mm, 26 * mm])
            info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
            stats = _stat_cards([
                ("PTS", str(p["ppg"])), ("REB", str(p["rpg"])), ("AST", str(p["apg"])),
                ("TS%", f"{p['ts_pct']}"), ("+/-", f"{'+' if pm >= 0 else ''}{pm}"),
            ], cols=5)
            card = Table([[info], [stats], [chart]], colWidths=[44 * mm])
            card.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            cards.append(card)
        while len(cards) % 2:
            cards.append("")
        rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
        grid = Table(rows, colWidths=[90 * mm, 90 * mm])
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 3),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story += [grid, Spacer(1, 10)]

    # ---- Mapa de tiro del equipo ----
    if rep["detail_ready"]:
        team_shots = shots_mod.shots_for_team(session, team_id)
        if team_shots:
            summ = shots_mod.shot_zone_summary(team_shots)
            story += [_section("Mapa de tiro del equipo"), Spacer(1, 5)]
            chart = RLImage(render_shotchart(team_shots, scale=42), width=72 * mm, height=67 * mm)
            legend = _p(f"{summ['attempts']} tiros · {summ['made']} anotados · {summ['pct']}%  "
                        "(<font color='#1FA463'>●</font> anotado · <font color='#D8453C'>●</font> fallado)", 8, MUTED)
            wrap = Table([[chart], [legend]], colWidths=[72 * mm])
            wrap.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
            story.append(wrap)

    story += [Spacer(1, 8),
              _p("Generado por PiScouting · datos FEB (LiveStats)", 7, MUTED, align=TA_CENTER)]

    doc.build(story)
    buf.seek(0)
    return buf
