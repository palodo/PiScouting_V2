"""Informe post-partido en PDF (vertical, una sección por página).

Hermano de `pdf_report.py` (que mira una temporada entera); este mira UN partido. La
identidad visual es la misma —navy de marca, naranja balón, fondo papel— pero el formato
es vertical porque las secciones son de dos columnas: una tabla y su lectura al lado.

Qué lleva, en este orden:
   portada · resumen ejecutivo · evolución del marcador · fases y tiempos muertos ·
   estadística avanzada (four factors) · economía de posesión · perfil de tiro ·
   impacto, banquillo y faltas · boxscore de cada equipo · producción individual ·
   rotaciones de cada equipo · claves de scouting · calidad del dato

La última página no es relleno: dice qué se ha validado contra el acta y qué es
estimación. Un informe que no distingue las dos cosas no se puede usar para decidir.
"""
from __future__ import annotations

import io
import math
import re
from typing import Optional

from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image as RLImage, KeepTogether, NextPageTemplate,
)
from sqlmodel import Session

from . import postgame
from .postgame import COURT_L, COURT_W, HOOP_D, THREE_R, CORNER_Y, CORNER_D

# ------------------------------ paleta (la del resto de la app) ------------------------
NAVY = colors.HexColor("#28344A")
INK = colors.HexColor("#20293A")
ACCENT = colors.HexColor("#FF5A1F")      # naranja balón
ACCENT_SOFT = colors.HexColor("#FFE7DC")
BLUE = colors.HexColor("#2F6FE0")
BLUE_SOFT = colors.HexColor("#E5EEFC")
MUTED = colors.HexColor("#7B8698")
FAINT = colors.HexColor("#AEB7C6")
LINE = colors.HexColor("#D9DEE8")
LINE_SOFT = colors.HexColor("#E9ECF3")
ZEBRA = colors.HexColor("#F6F7FA")
PAPER = colors.HexColor("#F7F3EA")
GOOD = colors.HexColor("#1F9D55")
BAD = colors.HexColor("#D6463C")
WOOD = colors.HexColor("#E0A526")

PW, PH = A4
MARGIN = 15 * mm
CONTENT_W = PW - 2 * MARGIN

_styles = getSampleStyleSheet()


# En español el separador decimal es la coma. Se aplica en UN sitio, al pintar: la API
# sigue devolviendo números de verdad (0.61), que es lo que quiere quien los consume.
_DEC = re.compile(r"(?<=\d)\.(?=\d)")


def _p(text, size=9, color=INK, bold=False, align=TA_LEFT, leading=None, font=None):
    return Paragraph(_DEC.sub(",", str(text)), ParagraphStyle(
        "x", parent=_styles["Normal"], fontSize=size,
        fontName=font or ("Helvetica-Bold" if bold else "Helvetica"),
        textColor=color, alignment=align, leading=leading or size + 3))


def _kicker(n: int, text: str):
    return _p(f"{n:02d} · {text.upper()}", 8, ACCENT, bold=True)


def _title(text, size=19):
    return _p(text, size, NAVY, bold=True, leading=size + 4)


def _sep(space=3):
    t = Table([[""]], colWidths=[CONTENT_W], rowHeights=[0.6])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, LINE)]))
    return t


def _signed(v) -> str:
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return "—"
    return f"+{v}" if v > 0 else str(v)


def _col(v) -> colors.Color:
    try:
        return GOOD if float(v) > 0 else (BAD if float(v) < 0 else MUTED)
    except (TypeError, ValueError):
        return MUTED


def _na(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


# ============================ bloques reutilizables ============================
def _clip(text, n=26) -> str:
    text = str(text)
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


# Palabras que no distinguen a un equipo de otro: lo que de verdad lo identifica suele ir
# detrás del patrocinador ("CMG HIDRÁULICA NB TORRENT" -> "NB TORRENT").
_FILLER = {"CB", "CD", "CLUB", "BALONCESTO", "BASKET", "BASQUET", "BÀSQUET", "DE", "DEL",
           "LA", "EL", "SAD", "SD", "UD", "CE", "AB", "BC"}


def _abbr(name: Optional[str], n: int = 14) -> str:
    """Nombre de equipo corto para cabeceras, barras y tablas estrechas.

    Primero tira las palabras genéricas del final ("CLOUD.GAL OURENSE BALONCESTO" ->
    "CLOUD.GAL OURENSE") y luego se queda con las últimas que quepan, porque el nombre
    propio del club suele ir detrás del patrocinador ("CMG HIDRÁULICA NB TORRENT" ->
    "NB TORRENT"). Nunca corta a media palabra salvo que una sola ya no quepa.
    """
    if not name:
        return "—"
    words = str(name).strip().split()
    if not words:
        return "—"
    if len(" ".join(words)) <= n:
        return " ".join(words)
    while len(words) > 1 and words[-1].upper().strip(".") in _FILLER:
        words.pop()
    if len(" ".join(words)) <= n:
        return " ".join(words)
    tail: list[str] = [words[-1]]
    for w in reversed(words[:-1]):
        if len(" ".join([w] + tail)) > n:
            break
        tail.insert(0, w)
    while len(tail) > 1 and tail[0].upper().strip(".") in _FILLER:
        tail.pop(0)
    out = " ".join(tail)
    # una sola palabra que se pasa por poco se deja entera: leer "RIGALLI-ALGINET" es
    # mejor que leer "RIGALLI-ALGIN…"
    return out if len(out) <= n + 3 else out[:n - 1].rstrip() + "…"


def _card(value, label, foot="", accent=False, w=None):
    bg = ACCENT_SOFT if accent else colors.HexColor("#EEF2F8")
    bd = ACCENT if accent else colors.HexColor("#C9D2E0")
    value = str(value)
    size = 17 if len(value) <= 7 else (14 if len(value) <= 10 else 11.5)
    rows = [[_p(_clip(label, 22).upper(), 6.6, MUTED, bold=True, leading=8)],
            [_p(value, size, INK, bold=True, leading=size + 2)]]
    heights = [10, 20]
    if foot:
        # dos líneas como mucho: la tarjeta tiene altura fija y lo que sobra se desborda
        rows.append([_p(_clip(foot, 46), 6.4, MUTED, leading=7.6)])
        heights.append(16)
    t = Table(rows, colWidths=[w] if w else None, rowHeights=heights)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.8, bd),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _row_of(cards, gap=4 * mm, width=None):
    width = width or CONTENT_W
    n = len(cards)
    if not n:
        return Spacer(1, 1)
    cw = (width - gap * (n - 1)) / n
    cells, widths = [], []
    for i, c in enumerate(cards):
        cells.append(c)
        widths.append(cw)
        if i < n - 1:
            cells.append("")
            widths.append(gap)
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _panel(title, body_flowables, width, accent=NAVY, bg=colors.white):
    inner = [[_p(title, 10.5, NAVY, bold=True)]] + [[f] for f in body_flowables]
    t = Table(inner, colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _note(text, width=None, accent=ACCENT, bg=ACCENT_SOFT):
    t = Table([[_p(text, 8.2, INK, leading=11)]], colWidths=[width or CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _table(head: list, rows: list[list], widths: list, aligns=None, size=7.6,
           zebra=True, bold_first=False, head_bg=colors.HexColor("#EEF2F8")):
    data = [[_p(h, 6.6, MUTED, bold=True,
                align=TA_RIGHT if (aligns and aligns[i] == "R") else TA_LEFT)
             for i, h in enumerate(head)]]
    for r in rows:
        line = []
        for i, cell in enumerate(r):
            if isinstance(cell, Paragraph) or isinstance(cell, Table):
                line.append(cell)
            else:
                line.append(_p(cell, size, INK, bold=(bold_first and i == 0),
                               align=TA_RIGHT if (aligns and aligns[i] == "R") else TA_LEFT))
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, LINE_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(style))
    return t


def _bar(label, value, maxv, width, color=ACCENT, suffix="%"):
    """Barra horizontal con su etiqueta: compara dos equipos de un vistazo."""
    frac = max(0.0, min(1.0, (value or 0) / maxv if maxv else 0))
    bw = width * 0.52
    filled = max(0.6, bw * frac)
    bar = Table([[""]], colWidths=[filled], rowHeights=[5])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    track = Table([[bar, ""]], colWidths=[filled, bw - filled], rowHeights=[5])
    track.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#E6EAF1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    t = Table([[_p(label, 7, MUTED), track, _p(f"{value}{suffix}", 7.4, INK, bold=True,
                                               align=TA_RIGHT)]],
              colWidths=[width * 0.22, bw, width * 0.26])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


# ============================ gráficos ============================
_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _font(size: int):
    """Fuente para los gráficos. Si el servidor no trae ninguna TTF, PIL usa la suya
    (diminuta pero legible): un informe sin etiquetas de eje es peor que uno feo."""
    from PIL import ImageFont
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()
def render_flow(flow: dict, home: str, away: str, w=1500, h=430) -> io.BytesIO:
    """Diferencia de marcador a lo largo del partido. Verde = manda el local."""
    img = Image.new("RGB", (w, h), "#FFFFFF")
    d = ImageDraw.Draw(img)
    pad_l, pad_r, pad_t, pad_b = 74, 20, 26, 44
    f_axis, f_lab = _font(21), _font(24)
    series = flow["series"] or [{"t": 0, "diff": 0}]
    end = max(s["t"] for s in series) or 2400
    top = max(12, max(abs(s["diff"]) for s in series) + 3)

    def X(t):
        return pad_l + (t / end) * (w - pad_l - pad_r)

    def Y(v):
        return pad_t + (top - v) / (2 * top) * (h - pad_t - pad_b)

    # rejilla por cuartos
    qlen = 600
    q = qlen
    while q < end:
        d.line([X(q), pad_t, X(q), h - pad_b], fill="#D9DEE8", width=2)
        q += qlen
    for v in (top, top / 2, 0, -top / 2, -top):
        y = Y(v)
        d.line([pad_l, y, w - pad_r, y], fill="#EEF1F6", width=1)
        d.text((12, y - 12), f"{int(v):+d}" if v else "0", fill="#8B93A4", font=f_axis)
    d.line([pad_l, Y(0), w - pad_r, Y(0)], fill="#AEB7C6", width=2)

    # área bajo la curva
    pts = [(X(s["t"]), Y(s["diff"])) for s in series]
    base = Y(0)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        poly = [(x0, base), (x0, y0), (x1, y0), (x1, base)]
        d.polygon(poly, fill="#DFF3E6" if y0 <= base else "#FBE3E0")
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d.line([x0, y0, x1, y0], fill="#FF5A1F", width=3)
        d.line([x1, y0, x1, y1], fill="#FF5A1F", width=3)

    labels = ["Q1", "Q2", "Q3", "Q4", "PR1", "PR2"]
    i = 0
    q = 0
    while q < end and i < len(labels):
        d.text(((X(q) + X(min(q + qlen, end))) / 2 - 14, h - pad_b + 10), labels[i],
               fill="#7B8698", font=f_axis)
        q += qlen
        i += 1
    d.text((pad_l + 8, pad_t + 2), f"{home}  manda", fill="#1F9D55", font=f_lab)
    d.text((pad_l + 8, h - pad_b - 30), f"{away}  manda", fill="#D6463C", font=f_lab)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def render_court(shots: list[dict], w=620, scale=2) -> io.BytesIO:
    """Media pista con los tiros. Verde = anotado, rojo = fallado.

    La pista se dibuja con la MISMA geometría con la que se clasifican las zonas
    (`postgame.COURT_L/COURT_W`), así que un tiro cae donde dice la tabla de zonas. Antes
    de calibrarla, los tiros salían repartidos más anchos que la pista pintada debajo.
    """
    px = COURT_W  # metros a lo ancho del lienzo
    py = COURT_L
    W = int(w * scale)
    H = int(W * py / px)
    M = W / px  # píxeles por metro
    img = Image.new("RGB", (W, H), "#F6EEDD")
    d = ImageDraw.Draw(img)
    line = "#C09A55"
    lw = max(2, int(1.6 * scale))

    def PX(dy):   # desvío lateral (m) -> x
        return W / 2 + dy * M

    def PY(depth):  # profundidad desde el fondo (m) -> y
        return H - depth * M

    # límites de la pista real (15 m) dentro del lienzo
    d.rectangle([PX(-7.5), PY(py), PX(7.5), PY(0)], outline=line, width=lw)
    # zona 4,90 x 5,80
    d.rectangle([PX(-2.45), PY(5.8), PX(2.45), PY(0)], outline=line, width=lw)
    r = 1.80 * M
    d.arc([PX(-1.8), PY(5.8) - r, PX(1.8), PY(5.8) + r], 180, 360, fill=line, width=lw)
    # aro y tablero
    d.line([PX(-0.9), PY(1.2), PX(0.9), PY(1.2)], fill=line, width=lw + 1)
    rr = 0.225 * M
    d.ellipse([PX(0) - rr, PY(HOOP_D) - rr, PX(0) + rr, PY(HOOP_D) + rr],
              outline=line, width=lw)
    # línea de 3: rectas de esquina + arco
    d.line([PX(-CORNER_Y), PY(0), PX(-CORNER_Y), PY(CORNER_D)], fill=line, width=lw)
    d.line([PX(CORNER_Y), PY(0), PX(CORNER_Y), PY(CORNER_D)], fill=line, width=lw)
    R = THREE_R * M
    d.arc([PX(0) - R, PY(HOOP_D) - R, PX(0) + R, PY(HOOP_D) + R], 180, 360,
          fill=line, width=lw)

    for s in shots:
        depth, dy = postgame.court_metres(s["hx"], s["hy"])
        x, y = PX(dy), PY(depth)
        rad = 5 * scale
        if s["made"]:
            d.ellipse([x - rad, y - rad, x + rad, y + rad], fill="#23A455",
                      outline="#FFFFFF", width=max(1, scale))
        else:
            k = rad * 0.95
            d.line([x - k, y - k, x + k, y + k], fill="#E0564B", width=max(2, scale + 1))
            d.line([x - k, y + k, x + k, y - k], fill="#E0564B", width=max(2, scale + 1))

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================ documento ============================
def build_postgame_pdf(session: Session, match_id: int) -> io.BytesIO:
    rep = postgame.build(session, match_id)
    if not rep:
        raise ValueError("Partido no encontrado")

    mt = rep["match"]
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4, topMargin=16 * mm, bottomMargin=14 * mm,
        leftMargin=MARGIN, rightMargin=MARGIN,
        title=f"Informe {mt['home']['name']} vs {mt['away']['name']}",
        author="PiScouting")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    cover = PageTemplate(id="cover", frames=[Frame(0, 0, PW, PH, leftPadding=0,
                                                   rightPadding=0, topPadding=0,
                                                   bottomPadding=0)],
                         onPage=lambda c, d: _cover_bg(c, d, rep))
    inner = PageTemplate(id="main", frames=[frame],
                         onPage=lambda c, d: _header_footer(c, d, rep))
    doc.addPageTemplates([cover, inner])

    S: list = []
    _cover(S, rep)
    # La portada tiene su propia plantilla (fondo oscuro, sin márgenes). Sin esto,
    # ReportLab la mantendría en TODO el documento.
    S.append(NextPageTemplate("main"))
    n = [0]

    def sec(label):
        n[0] += 1
        S.append(PageBreak())
        S.append(_kicker(n[0], label))
        S.append(Spacer(1, 1.5 * mm))

    _summary_page(S, rep, sec)
    if rep.get("flow"):
        _flow_page(S, rep, sec)
        _phases_page(S, rep, sec)
    _advanced_page(S, rep, sec)
    if rep.get("possessions"):
        _economy_page(S, rep, sec)
    if rep["shooting"]["shots"]["home"] or rep["shooting"]["shots"]["away"]:
        _shooting_page(S, rep, sec)
    _impact_page(S, rep, sec)
    _box_page(S, rep, sec, "home")
    _box_page(S, rep, sec, "away")
    _production_page(S, rep, sec)
    if rep.get("lineups"):
        _lineups_page(S, rep, sec, "home")
        _lineups_page(S, rep, sec, "away")
    _keys_page(S, rep, sec)
    _quality_page(S, rep, sec)

    doc.build(S)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------- portada
def _cover_bg(canvas, doc, rep):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#1B2436"))
    canvas.rect(0, 0, PW, PH, fill=1, stroke=0)
    # franja inferior algo más clara: separa la ficha del partido del titular
    canvas.setFillColor(colors.HexColor("#222C42"))
    canvas.rect(0, 0, PW, PH * 0.265, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, PH * 0.265, PW, 1.4, fill=1, stroke=0)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#8B93A4"))
    canvas.drawString(MARGIN, 12 * mm,
                      "Resultado oficial y play-by-play reconciliados. "
                      "Las métricas estimadas se identifican como tales.")
    canvas.restoreState()


def _cover(S, rep):
    mt = rep["match"]
    h, a = mt["home"], mt["away"]
    white = colors.white
    S.append(Spacer(1, 26 * mm))
    S.append(_p("PISCOUTING", 20, white, bold=True, align=TA_CENTER))
    S.append(_p("ANÁLISIS DE BALONCESTO FEB", 7.5, ACCENT, bold=True, align=TA_CENTER))
    S.append(Spacer(1, 30 * mm))
    S.append(_p("INFORME DE SCOUTING · PARTIDO", 9, ACCENT, bold=True, align=TA_CENTER))
    sub = " · ".join(x for x in [mt["competition"], mt.get("grupo"), mt.get("jornada")] if x)
    S.append(_p(sub, 8.5, colors.HexColor("#AEB7C6"), align=TA_CENTER))
    S.append(Spacer(1, 10 * mm))

    name_w = (PW - 2 * MARGIN) * 0.33
    score = Table([[_p(str(h["score"]), 40, white, bold=True, align=TA_RIGHT, leading=42),
                    _p("·", 30, ACCENT, bold=True, align=TA_CENTER, leading=42),
                    _p(str(a["score"]), 40, white, bold=True, align=TA_LEFT, leading=42)]],
                  colWidths=[26 * mm, 10 * mm, 26 * mm])
    score.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    win_h = mt["winner"] == "home"
    t = Table([[
        Table([[_p(h["name"].upper(), 13, white if win_h else colors.HexColor("#AEB7C6"),
                   bold=True, align=TA_RIGHT, leading=15)],
               [_p("LOCAL", 6.5, MUTED, bold=True, align=TA_RIGHT)]]),
        score,
        Table([[_p(a["name"].upper(), 13, white if not win_h else colors.HexColor("#AEB7C6"),
                   bold=True, align=TA_LEFT, leading=15)],
               [_p("VISITANTE", 6.5, MUTED, bold=True, align=TA_LEFT)]]),
    ]], colWidths=[name_w, 62 * mm, name_w])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(t)
    S.append(Spacer(1, 6 * mm))

    qs = "    ".join(f"Q{q['n']} {q['home']}-{q['away']}" for q in mt["quarters"])
    S.append(_p(qs or "—", 8.5, colors.HexColor("#AEB7C6"), align=TA_CENTER))
    S.append(Spacer(1, 20 * mm))

    head = rep["summary"]["headline"]
    S.append(Table([[_p(head, 21, white, bold=True, leading=25)]],
                   colWidths=[CONTENT_W],
                   style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), MARGIN),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), MARGIN)])))
    S.append(Spacer(1, 4 * mm))
    S.append(Table([[_p(rep["summary"]["lead"], 9, colors.HexColor("#AEB7C6"), leading=13)]],
                   colWidths=[CONTENT_W],
                   style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), MARGIN),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), MARGIN)])))
    S.append(Spacer(1, 42 * mm))

    fecha = mt.get("date") or "—"
    if fecha != "—":
        y, mo, dd = fecha.split("-")
        fecha = f"{dd}/{mo}/{y}"
    foot = [
        ("FECHA / LUGAR", f"{fecha}<br/>{mt.get('venue') or '—'}"),
        ("DESCANSO", mt.get("halftime") or "—"),
        ("NIVEL DE DATO", rep["quality"]["level"].capitalize()),
    ]
    cells = []
    for label, value in foot:
        cells.append(Table([[_p(label, 6.5, MUTED, bold=True)],
                            [_p(value, 8, colors.white, bold=True, leading=10)]],
                           colWidths=[(CONTENT_W - 12 * mm) / 3],
                           style=TableStyle([
                               ("LINEABOVE", (0, 0), (-1, 0), 1.4, ACCENT),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (0, 0), 4),
                           ])))
    t = Table([[cells[0], "", cells[1], "", cells[2]]],
              colWidths=[(CONTENT_W - 12 * mm) / 3, 6 * mm, (CONTENT_W - 12 * mm) / 3,
                         6 * mm, (CONTENT_W - 12 * mm) / 3])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), MARGIN if False else 0)]))
    S.append(Table([[t]], colWidths=[CONTENT_W],
                   style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), MARGIN),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), MARGIN)])))


def _header_footer(canvas, doc, rep):
    mt = rep["match"]
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 7.6)
    canvas.setFillColor(NAVY)
    canvas.drawString(MARGIN, PH - 11 * mm, "Informe de scouting · partido")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    sub = f"{mt['home']['name']} vs {mt['away']['name']}"
    extra = " · ".join(x for x in [mt["competition"], mt.get("grupo"),
                                   (mt.get("date") or "")] if x)
    canvas.drawString(MARGIN, PH - 14.6 * mm, f"{sub} · {extra}"[:120])
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(ACCENT)
    canvas.drawRightString(PW - MARGIN, PH - 11.6 * mm, f"{doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.7)
    canvas.line(MARGIN, PH - 16.5 * mm, PW - MARGIN, PH - 16.5 * mm)

    canvas.setFont("Helvetica", 6.8)
    canvas.setFillColor(FAINT)
    canvas.drawString(MARGIN, 9 * mm, "PiScouting · análisis de baloncesto FEB")
    canvas.drawRightString(PW - MARGIN, 9 * mm,
                           "Fuente: FEB LiveStats · métricas e interpretación PiScouting")
    canvas.restoreState()


# ---------------------------------------------------------------- 01 resumen
def _summary_page(S, rep, sec):
    sec("Resumen ejecutivo")
    sm = rep["summary"]
    S.append(_title(sm["headline"]))
    S.append(Spacer(1, 3 * mm))
    S.append(_note(f"<b>Lectura central.</b> {sm['lead']}"))
    S.append(Spacer(1, 4 * mm))
    S.append(_row_of([_card(c["value"], c["label"], c["foot"]) for c in sm["cards"][:5]]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    left = []
    for d in sm["decided"]:
        left.append(_p(f"<b>{d['title']}.</b> {d['text']}", 8.4, INK, leading=11.5))
        left.append(Spacer(1, 2 * mm))
    right = []
    for g in sm["signals"]:
        right.append(_p(f"<b>{g['title']}:</b> {g['text']}", 8.4, INK, leading=11.5))
        right.append(Spacer(1, 2 * mm))
    body = Table([[_panel("Qué decidió el partido", left or [_p("—", 8)], half),
                   "",
                   _panel("Señales de juego", right or [_p("—", 8)], half, accent=BLUE)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 5 * mm))
    k = rep["keys"]
    S.append(_note(
        f"<b>Lectura para preparar a ambos:</b> a {k['home']['team']} hay que quitarle "
        f"{k['home']['take_away'][0]}; a {k['away']['team']}, {k['away']['take_away'][0]}.",
        accent=GOOD, bg=colors.HexColor("#E4F5E9")))


# ---------------------------------------------------------------- 02 evolución
def _flow_page(S, rep, sec):
    sec("Evolución del marcador")
    fl, mt = rep["flow"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    lt = fl["lead_time"]
    leader = hn if lt["home"] >= lt["away"] else an
    S.append(_title(f"{leader} mandó {max(lt['home_label'], lt['away_label'], key=lambda s: len(s)) if False else (lt['home_label'] if lt['home'] >= lt['away'] else lt['away_label'])} de los 40 minutos"))
    S.append(Spacer(1, 3 * mm))
    img = render_flow(fl, hn, an)
    S.append(RLImage(img, width=CONTENT_W, height=CONTENT_W * 430 / 1500))
    S.append(Spacer(1, 4 * mm))
    S.append(_row_of([
        _card(lt["home_label"], f"{_abbr(hn, 16)} por delante",
              f"máx. +{fl['max_lead']['home']['pts']} · {fl['max_lead']['home']['at']}"),
        _card(lt["away_label"], f"{_abbr(an, 16)} por delante",
              f"máx. +{fl['max_lead']['away']['pts']} · {fl['max_lead']['away']['at']}"),
        _card(str(fl["lead_changes"]), "Cambios de líder", f"{fl['ties']} empate(s)"),
        _card(fl["droughts"]["home"]["label"] if fl["droughts"]["home"]["seconds"] >=
              fl["droughts"]["away"]["seconds"] else fl["droughts"]["away"]["label"],
              "Sequía más larga",
              (_abbr(hn) if fl["droughts"]["home"]["seconds"] >= fl["droughts"]["away"]["seconds"]
               else _abbr(an)) + " · " +
              (fl["droughts"]["home"]["from"] if fl["droughts"]["home"]["seconds"] >=
               fl["droughts"]["away"]["seconds"] else fl["droughts"]["away"]["from"])),
    ]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    rows = [[_abbr(hn) if r["is_home"] else _abbr(an), r["run"],
             f"{r['from_score']} → {r['to_score']}",
             f"{r['from_clock']} → {r['to_clock']}"] for r in fl["runs"]]
    runs_tbl = _table(["EQUIPO", "PARCIAL", "MARCADOR", "RELOJ"], rows or [["—", "—", "—", "—"]],
                      [half * 0.26, half * 0.16, half * 0.29, half * 0.29], bold_first=True)
    left = [_p("Rachas sin respuesta (6+ puntos)", 10.5, NAVY, bold=True), Spacer(1, 2 * mm),
            runs_tbl, Spacer(1, 1.5 * mm),
            _p("Marcador oficial local-visitante, tomado justo antes de la primera canasta "
               "de la racha.", 6.8, MUTED, leading=8.5)]

    txt = []
    if fl["runs"]:
        r = fl["runs"][0]
        who = hn if r["is_home"] else an
        txt.append(f"La racha que más pesó fue el {r['run']} de {who}: de {r['from_score']} "
                   f"({r['from_clock']}) a {r['to_score']} ({r['to_clock']}).")
    txt.append(f"{hn} estuvo por delante {lt['home_label']} y {an}, {lt['away_label']}; "
               f"{fl['ties']} empate(s) y {fl['lead_changes']} cambio(s) de líder.")
    d_h, d_a = fl["droughts"]["home"], fl["droughts"]["away"]
    txt.append(f"Sequías: {hn} pasó {d_h['label']} sin anotar desde {d_h['from']}; "
               f"{an}, {d_a['label']} desde {d_a['from']}.")
    right = []
    for t in txt:
        right.append(_p(t, 8.4, INK, leading=11.5))
        right.append(Spacer(1, 2 * mm))

    body = Table([[Table([[f] for f in left], colWidths=[half]), "",
                   _panel("Qué significa", right, half, accent=BLUE)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)


# ---------------------------------------------------------------- 03 fases
def _phases_page(S, rep, sec):
    sec("Fases, entradas y salidas de cada cuarto")
    ph, mt = rep["phases"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]

    best = max(ph["quarters"], key=lambda q: abs(q["open3_diff"]), default=None)
    title = "Arranques y cierres de cada cuarto"
    if best and abs(best["open3_diff"]) >= 5:
        who = hn if best["open3_diff"] > 0 else an
        title = f"{who} ganó el arranque del Q{best['quarter']} por {best['open3']}"
    S.append(_title(title))
    S.append(Spacer(1, 3 * mm))

    def cell(txt, diff):
        return _p(f'{txt} <font color="#{_col(diff).hexval()[2:]}">({_signed(diff)})</font>',
                  7.6, INK)

    rows = []
    for q in ph["quarters"]:
        rows.append([f"Q{q['quarter']}", cell(q["open3"], q["open3_diff"]),
                     cell(q["mid"], q["mid_diff"]), cell(q["close2"], q["close2_diff"]),
                     _p(q["total"], 8, INK, bold=True)])
    w = CONTENT_W
    S.append(_table(["PERIODO", "PRIMEROS 3 MIN", "TRAMO CENTRAL", "ÚLTIMOS 2 MIN", "CUARTO"],
                    rows, [w * 0.14, w * 0.22, w * 0.22, w * 0.22, w * 0.20],
                    bold_first=True))
    S.append(Spacer(1, 1.5 * mm))
    S.append(_p(f"Parciales expresados {hn}-{an}.", 6.8, MUTED))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    trows = [[_abbr(hn if t["is_home"] else an, 12), t["at"], t["score"], t["before"],
              t["after"],
              _p(_signed(t["swing"]), 7.6, _col(t["swing"]), bold=True, align=TA_RIGHT)]
             for t in ph["timeouts"]]
    tt = _table(["PIDE", "RELOJ", "MARCA.", "2' ANTES", "2' DESP.", "SALDO"],
                trows or [["—"] * 6],
                [half * 0.21, half * 0.16, half * 0.19, half * 0.14, half * 0.16, half * 0.14],
                aligns=[None, None, "R", "R", "R", "R"], size=7.2, bold_first=True)
    left = [_p("Tiempos muertos · 2 minutos antes y después", 10.5, NAVY, bold=True),
            Spacer(1, 2 * mm), tt, Spacer(1, 1.5 * mm),
            _p("Parciales desde el punto de vista de quien pide el tiempo muerto. "
               "Muestra pequeña: lectura descriptiva.", 6.8, MUTED, leading=8.5)]

    op = [q for q in ph["quarters"]]
    o_h = sum(int(q["open3"].split("-")[0]) for q in op)
    o_a = sum(int(q["open3"].split("-")[1]) for q in op)
    c_h = sum(int(q["close2"].split("-")[0]) for q in op)
    c_a = sum(int(q["close2"].split("-")[1]) for q in op)
    periodos = "los cuatro cuartos" if len(op) <= 4 else f"los {len(op)} periodos"
    txt = [f"Sumando {periodos}, los primeros 3 minutos fueron {o_h}-{o_a} y los "
           f"últimos 2, {c_h}-{c_a}.",
           f"{hn} ganó {sum(1 for q in op if q['open3_diff'] > 0)} de {len(op)} arranques y "
           f"{sum(1 for q in op if q['close2_diff'] > 0)} de {len(op)} cierres."]
    tos = ph["timeouts"]
    if tos:
        hteam = [t for t in tos if t["is_home"]]
        ateam = [t for t in tos if not t["is_home"]]
        txt.append(f"{hn} pidió {len(hteam)} tiempo(s) muerto(s) y {an}, {len(ateam)}. "
                   f"El saldo medio de los 2 minutos siguientes fue "
                   f"{_signed(sum(t['swing'] for t in hteam) / len(hteam)) if hteam else '—'} "
                   f"y {_signed(sum(t['swing'] for t in ateam) / len(ateam)) if ateam else '—'}.")
    right = []
    for t in txt:
        right.append(_p(t, 8.4, INK, leading=11.5))
        right.append(Spacer(1, 2 * mm))

    body = Table([[Table([[f] for f in left], colWidths=[half]), "",
                   _panel("Lectura", right, half, accent=BLUE)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)


# ---------------------------------------------------------------- 04 avanzada
def _advanced_page(S, rep, sec):
    sec("Estadística avanzada")
    adv, mt = rep["advanced"], rep["match"]
    h, a = adv["home"], adv["away"]
    hn, an = mt["home"]["name"], mt["away"]["name"]

    wins = []
    if h["efg"] != a["efg"]:
        wins.append(("eFG%", hn if h["efg"] > a["efg"] else an))
    if h["tov_pct"] != a["tov_pct"]:
        wins.append(("el balón", hn if h["tov_pct"] < a["tov_pct"] else an))
    if h["orb_pct"] != a["orb_pct"]:
        wins.append(("el rebote", hn if h["orb_pct"] > a["orb_pct"] else an))
    S.append(_title("Quién ganó cada uno de los cuatro factores"))
    S.append(Spacer(1, 3 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    rows = [
        ["Posesiones reales", _na(h["poss_real"]), _na(a["poss_real"])],
        ["Posesiones estimadas", h["poss_est"], a["poss_est"]],
        ["Ef. ofensiva (pts/100 pos.)", h["off_rtg"], a["off_rtg"]],
        ["Ef. defensiva", h["def_rtg"], a["def_rtg"]],
        ["Ef. neta", _signed(h["net_rtg"]), _signed(a["net_rtg"])],
        ["eFG%", f"{h['efg']}%", f"{a['efg']}%"],
        ["TS%", f"{h['ts']}%", f"{a['ts']}%"],
        ["TOV%", f"{h['tov_pct']}%", f"{a['tov_pct']}%"],
        ["ORB%", f"{h['orb_pct']}%", f"{a['orb_pct']}%"],
        ["DRB%", f"{h['drb_pct']}%", f"{a['drb_pct']}%"],
        ["FTr", f"{h['ftr']}%", f"{a['ftr']}%"],
        ["Volumen de triple", f"{h['three_rate']}%", f"{a['three_rate']}%"],
        ["% canastas asistidas", f"{h['ast_pct']}%", f"{a['ast_pct']}%"],
        ["Asistencias / pérdidas", h["ast_to"], a["ast_to"]],
    ]
    tbl = _table(["MÉTRICA", _abbr(hn).upper(), _abbr(an).upper()], rows,
                 [half * 0.46, half * 0.27, half * 0.27],
                 aligns=[None, "R", "R"], bold_first=False)

    ff = []
    for label, key, better, mx in (("eFG%", "efg", "mayor es mejor", 70),
                                   ("TOV%", "tov_pct", "menor es mejor", 30),
                                   ("ORB%", "orb_pct", "mayor es mejor", 55),
                                   ("FTr", "ftr", "mayor es mejor", 60)):
        ff.append(Table([[_p(label, 9.5, NAVY, bold=True),
                          _p(better, 6.8, MUTED, align=TA_RIGHT)]],
                        colWidths=[half * 0.5, half * 0.42]))
        ff.append(_bar(_abbr(hn, 12), h[key], mx, half * 0.92, color=ACCENT))
        ff.append(_bar(_abbr(an, 12), a[key], mx, half * 0.92, color=WOOD))
        ff.append(Spacer(1, 1.5 * mm))

    body = Table([[tbl, "", _panel("Four Factors", ff, half)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 4 * mm))
    S.append(_note(
        f"Las dos eficiencias se calculan sobre el ritmo del partido ({adv['pace']} "
        f"posesiones), que es el mismo para los dos: comparar «puntos por 100» con "
        f"denominadores distintos inventa una diferencia que no existe. TOV%, ORB% y FTr "
        f"van sobre las posesiones propias.", accent=BLUE, bg=BLUE_SOFT))


# ---------------------------------------------------------------- 05 economía
def _economy_page(S, rep, sec):
    sec("Economía de posesión · play-by-play")
    po, mt = rep["possessions"], rep["match"]
    h, a = po["home"], po["away"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    faster = hn if h["fast_break"] > a["fast_break"] else an
    S.append(_title(f"La carrera fue de {faster}" if h["fast_break"] != a["fast_break"]
                    else "De dónde salieron los puntos"))
    S.append(Spacer(1, 3 * mm))
    S.append(_row_of([
        _card(f"{h['second_chance']}-{a['second_chance']}", "Pts 2ª oportunidad",
              f"en {h['second_chance_poss']}-{a['second_chance_poss']} posesiones"),
        _card(f"{h['off_turnovers']}-{a['off_turnovers']}", "Pts tras pérdida",
              f"en {h['off_turnovers_poss']}-{a['off_turnovers_poss']} posesiones"),
        _card(f"{h['fast_break']}-{a['fast_break']}", "Pts rápidos (hasta 8 s)",
              f"posesión media {h['avg_seconds']}s / {a['avg_seconds']}s"),
        _card(f"{h['empty']}/{h['poss']}", "Posesiones vacías",
              f"{_abbr(an)}: {a['empty']}/{a['poss']}"),
    ]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 5 * mm) / 2

    def origin_panel(side, name, color):
        body = []
        for o in side["by_origin"]:
            body.append(_p(f"{o['label']} · <font color='#7B8698'>{o['pts']} pts en "
                           f"{o['poss']} pos.</font>", 7.2, INK))
            body.append(_bar("", o["ppp"], 1.6, half * 0.92, color=color, suffix=""))
        return _panel(f"{_abbr(name, 24)} · puntos por posesión", body, half, accent=color)

    body = Table([[origin_panel(h, hn, ACCENT), "", origin_panel(a, an, WOOD)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 5 * mm))

    third = (CONTENT_W - 10 * mm) / 3
    b1 = [_p(f"{hn} sumó <b>{h['second_chance']} puntos de segunda oportunidad</b> en "
             f"{h['second_chance_poss']} posesiones con rebote ofensivo; {an}, "
             f"{a['second_chance']} en {a['second_chance_poss']}.", 8.2, INK, leading=11)]
    b2 = [_p(f"{hn} anotó {h['off_turnovers']} puntos tras pérdida rival en "
             f"{h['off_turnovers_poss']} posesiones; {an}, {a['off_turnovers']} en "
             f"{a['off_turnovers_poss']}.", 8.2, INK, leading=11)]
    best_h = max(h["by_origin"], key=lambda o: o["ppp"])
    best_a = max(a["by_origin"], key=lambda o: o["ppp"])
    b3 = [_p(f"Donde mejor rindió {hn}: {best_h['label'].lower()} ({best_h['ppp']} pts por "
             f"posesión). {an}: {best_a['label'].lower()} ({best_a['ppp']}).",
             8.2, INK, leading=11)]
    tri = Table([[_panel("Segundas oportunidades", b1, third),
                  "", _panel("Puntos tras pérdida", b2, third),
                  "", _panel("Según el origen", b3, third)]],
                colWidths=[third, 5 * mm, third, 5 * mm, third])
    tri.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(tri)
    S.append(Spacer(1, 4 * mm))
    S.append(_note(
        "<b>Definiciones:</b> segunda oportunidad = puntos anotados tras un rebote ofensivo "
        "dentro de la misma posesión · tras pérdida = posesiones que empiezan por pérdida "
        "rival · rápidos = puntos en los primeros 8 s de una posesión que empieza con robo, "
        "rebote defensivo o pérdida rival. Todo calculado sobre posesiones reconstruidas "
        "una a una, no estimadas.", accent=BLUE, bg=BLUE_SOFT))


# ---------------------------------------------------------------- 06 tiro
def _shooting_page(S, rep, sec):
    sec("Perfil de tiro")
    sh, mt = rep["shooting"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    zh = {z["zone"]: z for z in sh["zones"]["home"]}
    S.append(_title("Dónde tiró cada equipo y qué sacó de cada zona"))
    S.append(Spacer(1, 3 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    imgs = []
    for side, name in (("home", hn), ("away", an)):
        buf = render_court(sh["shots"][side])
        img = RLImage(buf, width=half * 0.95, height=half * 0.95 * COURT_L / COURT_W)
        imgs.append(_panel(f"Mapa de tiro · {_abbr(name, 24)}", [img], half))
    body = Table([[imgs[0], "", imgs[1]]], colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 1.5 * mm))
    S.append(_p("Verde = anotado · rojo = fallado. Coordenadas de la FEB sobre media pista "
                "calibrada contra el valor real de cada tiro.", 6.8, MUTED))
    S.append(Spacer(1, 4 * mm))

    rows = []
    za = {z["zone"]: z for z in sh["zones"]["away"]}
    for z in postgame.ZONES:
        a_, b_ = zh[z], za[z]
        rows.append([postgame.ZONE_LABEL[z],
                     f"{a_['made']}/{a_['att']}", f"{a_['pps']}", f"{a_['share']}%",
                     f"{b_['made']}/{b_['att']}", f"{b_['pps']}", f"{b_['share']}%"])
    w = CONTENT_W
    S.append(_table(["ZONA", f"{_abbr(hn, 12).upper()} TC", "PTS/TIRO", "VOL.",
                     f"{_abbr(an, 12).upper()} TC", "PTS/TIRO", "VOL."], rows,
                    [w * 0.22, w * 0.13, w * 0.11, w * 0.1, w * 0.13, w * 0.11, w * 0.1],
                    aligns=[None, "R", "R", "R", "R", "R", "R"], bold_first=True))
    S.append(Spacer(1, 4 * mm))

    hrows = []
    for side, name in (("home", hn), ("away", an)):
        for hf in sh["halves"][side]:
            hrows.append([f"{_abbr(name, 15)} · {hf['half']}", hf["tc"], hf["t3"], hf["tl"],
                          str(hf["pts"])])
    left = [_p("Por mitades", 10.5, NAVY, bold=True), Spacer(1, 2 * mm),
            _table(["EQUIPO", "TC", "TRIPLES", "TL", "PUNTOS"], hrows,
                   [half * 0.37, half * 0.15, half * 0.17, half * 0.15, half * 0.16],
                   aligns=[None, "R", "R", "R", "R"], bold_first=True)]

    def read(side, name):
        z = {x["zone"]: x for x in sh["zones"][side]}
        rim = z["restringida"]
        c3, f3 = z["triple_esquina"], z["triple_frontal"]
        return (f"{_abbr(name, 24)}: {rim['made']}/{rim['att']} en zona restringida "
                f"({rim['share']}% de sus tiros), {f3['made']}/{f3['att']} en triples "
                f"frontales y {c3['made']}/{c3['att']} desde la esquina.")

    right = [_p(read("home", hn), 8.4, INK, leading=11.5), Spacer(1, 2 * mm),
             _p(read("away", an), 8.4, INK, leading=11.5)]
    body = Table([[Table([[f] for f in left], colWidths=[half]), "",
                   _panel("Lectura", right, half, accent=BLUE)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)


# ---------------------------------------------------------------- 07 impacto
def _impact_page(S, rep, sec):
    sec("Impacto, banquillo y faltas")
    im, mt = rep["impact"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    tops = im["top"]
    best = max(tops["home"] + tops["away"], key=lambda t: t["gmsc"], default=None)
    S.append(_title(f"{best['short']} fue el mejor del partido ({best['gmsc']} Game Score)"
                    if best else "Impacto individual"))
    S.append(Spacer(1, 3 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    panels = []
    for side, name in (("home", hn), ("away", an)):
        rows = [[t["short"], t["min"], str(t["gmsc"]), str(t["val"]), str(t["pts"]),
                 _p(_signed(t["plus_minus"]), 7.6, _col(t["plus_minus"]), bold=True,
                    align=TA_RIGHT)] for t in tops[side]]
        panels.append([_p(f"Top 3 · {_abbr(name, 24)}", 10.5, NAVY, bold=True),
                       Spacer(1, 2 * mm),
                       _table(["JUGADOR", "MIN", "GAME SCORE", "VAL", "PTS", "+/-"], rows,
                              [half * 0.28, half * 0.15, half * 0.21, half * 0.11,
                               half * 0.11, half * 0.12],
                              aligns=[None, "R", "R", "R", "R", "R"], bold_first=True)])
    body = Table([[Table([[f] for f in panels[0]], colWidths=[half]), "",
                   Table([[f] for f in panels[1]], colWidths=[half])]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 1.5 * mm))
    S.append(_p("Ranking por Game Score (Hollinger, versión de un partido). "
                "El PER solo se usa en informes de temporada.", 6.8, MUTED))
    S.append(Spacer(1, 4 * mm))

    # Sin play-by-play no hay titulares (el acta de la FEB deja ese campo vacío) y la
    # tabla diría que los diez salieron del banquillo.
    if not rep.get("starters"):
        S.append(_note("Titulares frente a suplentes no disponible: hace falta el "
                       "play-by-play del partido, porque el acta de la FEB no publica "
                       "quién salió de inicio.", accent=BLUE, bg=BLUE_SOFT))
        return

    S.append(_p("Titulares frente a suplentes", 10.5, NAVY, bold=True))
    S.append(Spacer(1, 2 * mm))
    rows = []
    for side, name in (("home", hn), ("away", an)):
        for u in im["units"][side]:
            rows.append([f"{_abbr(name, 15)} · {u['group']}", str(u["min"]), str(u["pts"]),
                         f"{u['share']}%", str(u["pts40"]), f"{u['ts']}%", str(u["tov"])])
    w = CONTENT_W
    S.append(_table(["GRUPO", "MIN", "PTS", "% DEL EQUIPO", "PTS/40", "TS%", "PÉRD."], rows,
                    [w * 0.3, w * 0.1, w * 0.1, w * 0.16, w * 0.12, w * 0.12, w * 0.1],
                    aligns=[None, "R", "R", "R", "R", "R", "R"], bold_first=True))
    S.append(Spacer(1, 1.5 * mm))
    S.append(_p("Titularidad tomada del play-by-play (los cinco que saltan en el 10:00 del "
                "Q1): el acta de la FEB no publica ese campo.", 6.8, MUTED))
    S.append(Spacer(1, 4 * mm))

    if im.get("fouls"):
        S.append(_p("Faltas y bonus", 10.5, NAVY, bold=True))
        S.append(Spacer(1, 2 * mm))
        rows = []
        for side, name in (("home", hn), ("away", an)):
            f = im["fouls"][side]
            early = " · ".join(f"{e['short']} ({e['at']})" for e in f["early_two"]) or "—"
            rows.append([_abbr(name, 16), " · ".join(str(x) for x in f["by_quarter"]),
                         str(f["total"]), f["opp_bonus_at"] or "—",
                         f"{f['opp_ft_made']}/{f['opp_ft_attempts']}", early])
        S.append(_table(["EQUIPO", "FALTAS POR CUARTO", "TOTAL", "RIVAL EN BONUS",
                         "TL DEL RIVAL", "2 FALTAS EN 1ª MITAD"], rows,
                        [w * 0.15, w * 0.16, w * 0.08, w * 0.15, w * 0.11, w * 0.35],
                        size=7.2, bold_first=True))


# ---------------------------------------------------------------- 08/09 boxscore
def _box_page(S, rep, sec, side):
    mt = rep["match"]
    name = mt[side]["name"]
    sec("Jugadores")
    S.append(_title(f"Box score · {name}"))
    S.append(Spacer(1, 3 * mm))
    rows = []
    for b in rep["box"][side]:
        label = f"#{b['dorsal'] or '—'} {b['name']}"
        if b["starter"]:
            label += "  <font color='#FF5A1F' size=6><b>TIT</b></font>"
        rows.append([_p(label, 7.4, INK), b["min"], _p(str(b["pts"]), 7.6, INK, bold=True,
                                                       align=TA_RIGHT),
                     b["tc"], b["t3"], b["tl"], str(b["oreb"]), str(b["dreb"]),
                     str(b["ast"]), str(b["tov"]), str(b["stl"]), str(b["pf"]),
                     str(b["val"]),
                     _p(_signed(b["plus_minus"]), 7.4, _col(b["plus_minus"]), bold=True,
                        align=TA_RIGHT)])
    tot = rep["box"]["totals"][side]
    rows.append([_p("<b>Totales</b>", 7.6, INK), "",
                 _p(f"<b>{tot['pts']}</b>", 7.6, INK, align=TA_RIGHT),
                 tot["tc"], tot["t3"], tot["tl"], str(tot["oreb"]), str(tot["dreb"]),
                 str(tot["ast"]), str(tot["tov"]), str(tot["stl"]), str(tot["pf"]), "", ""])
    w = CONTENT_W
    widths = [w * 0.235, w * 0.06, w * 0.05, w * 0.07, w * 0.065, w * 0.065, w * 0.045,
              w * 0.045, w * 0.045, w * 0.045, w * 0.05, w * 0.045, w * 0.05, w * 0.07]
    al = [None, "R", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R"]
    t = _table(["JUGADOR", "MIN", "PTS", "TC", "T3", "TL", "RO", "RD", "AS", "PÉR",
                "ROB", "FC", "VAL", "+/-"], rows, widths, aligns=al, size=7.4)
    t.setStyle(TableStyle([("LINEABOVE", (0, len(rows)), (-1, len(rows)), 0.9, NAVY),
                           ("BACKGROUND", (0, len(rows)), (-1, len(rows)),
                            colors.HexColor("#EEF2F8"))]))
    S.append(t)
    S.append(Spacer(1, 4 * mm))

    box = rep["box"][side]
    third = (CONTENT_W - 10 * mm) / 3
    scorers = sorted(box, key=lambda b: -b["pts"])[:4]
    b1 = [_p(" · ".join(f"<b>{b['short']}</b> {b['pts']}" for b in scorers if b["pts"]),
             8.2, INK, leading=11)]
    reb = sorted(box, key=lambda b: -b["treb"])[:3]
    b2 = [_p(" · ".join(f"<b>{b['short']}</b> {b['treb']} ({b['oreb']} of.)" for b in reb
                        if b["treb"]) or "—", 8.2, INK, leading=11)]
    alerts = []
    for b in box:
        if b["tov"] >= 4:
            alerts.append(f"<b>{b['short']}</b>: {b['tov']} pérdidas")
        if b["plus_minus"] <= -10:
            alerts.append(f"<b>{b['short']}</b>: {_signed(b['plus_minus'])}")
        if b["pf"] >= 4:
            alerts.append(f"<b>{b['short']}</b>: {b['pf']} faltas")
    b3 = [_p(" · ".join(alerts[:4]) or "Sin alertas destacadas.", 8.2, INK, leading=11)]
    tri = Table([[_panel("Anotación", b1, third), "", _panel("Rebote", b2, third),
                  "", _panel("Alertas", b3, third, accent=BAD)]],
                colWidths=[third, 5 * mm, third, 5 * mm, third])
    tri.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(tri)
    S.append(Spacer(1, 3 * mm))
    S.append(_note("+/- oficial validado contra el play-by-play. En un partido depende de "
                   "compañeros, rivales y momento: sirve para elegir vídeo, no para fijar "
                   "jerarquías.", accent=BLUE, bg=BLUE_SOFT))


# ---------------------------------------------------------------- 10 producción
def _production_page(S, rep, sec):
    sec("Producción individual")
    mt = rep["match"]
    S.append(_title("Uso, eficiencia y producción ofensiva"))
    S.append(Spacer(1, 3 * mm))
    w = CONTENT_W
    for side, name in (("home", mt["home"]["name"]), ("away", mt["away"]["name"])):
        S.append(_p(name, 10.5, NAVY, bold=True))
        S.append(Spacer(1, 1.5 * mm))
        rows = []
        for p in rep["production"][side]:
            rows.append([f"#{p['dorsal'] or '—'} {p['short']}", str(p["min"]),
                         f"{p['usg']}%", _na(p["ts"], "%"), str(p["gmsc"]),
                         str(p["pprod"]), _na(p["ortg"]), _na(p["floor"], "%"),
                         str(p["stops"]),
                         _p(_signed(p["plus_minus"]), 7.4, _col(p["plus_minus"]), bold=True,
                            align=TA_RIGHT)])
        S.append(_table(["JUGADOR", "MIN", "%USO", "TS%", "GMSC", "PTS PROD.",
                         "EF. OF.", "FLOOR%", "STOPS", "+/-"], rows,
                        [w * 0.23, w * 0.07, w * 0.08, w * 0.08, w * 0.08, w * 0.11,
                         w * 0.09, w * 0.09, w * 0.08, w * 0.08],
                        aligns=[None] + ["R"] * 9, size=7.3, bold_first=True))
        S.append(Spacer(1, 4 * mm))
    S.append(_note(
        "<b>%Uso</b> del boxscore estándar. <b>Pts producidos</b>, <b>eficiencia "
        "ofensiva individual</b>, <b>Floor%</b> y <b>Stops</b>: Dean Oliver "
        "(<i>Basketball on Paper</i>), implementación oliver_bref_v1. Son ESTIMACIONES "
        "y en un solo partido tienen muchísima varianza; eficiencia y Floor% solo se "
        "muestran con 10+ minutos.", accent=BLUE, bg=BLUE_SOFT))


# ---------------------------------------------------------------- 11/12 rotaciones
def _lineups_page(S, rep, sec, side):
    sec("Rotaciones")
    li = rep["lineups"][side]
    mt = rep["match"]
    name = mt[side]["name"]
    best_pair = max(li["pairs"], key=lambda p: p["plus_minus"], default=None)
    title = f"Rotaciones · {name}"
    if best_pair:
        title = f"{name}: la pareja {' - '.join(best_pair['players'])} ({_signed(best_pair['plus_minus'])})"
    S.append(_title(title, size=16))
    S.append(Spacer(1, 3 * mm))

    half = (CONTENT_W - 5 * mm) / 2
    rows = [[" · ".join(u["players"]), u["min"],
             _p(_signed(u["plus_minus"]), 7.4, _col(u["plus_minus"]), bold=True,
                align=TA_RIGHT), u["partial"]] for u in li["units"]]
    left = [_p("Quintetos con 1:48 o más", 10.5, NAVY, bold=True), Spacer(1, 2 * mm),
            _table(["QUINTETO", "MIN", "+/-", "PARCIAL"], rows or [["—"] * 4],
                   [half * 0.52, half * 0.15, half * 0.14, half * 0.17],
                   aligns=[None, "R", "R", "R"], size=7),
            Spacer(1, 1.5 * mm),
            _p(f"{li['distinct']} quintetos distintos" +
               (f" · quinteto inicial {li['starting']['min']} min "
                f"({_signed(li['starting']['plus_minus'])})" if li["starting"] else ""),
               6.8, MUTED)]

    prows = [[" + ".join(p["players"]), str(p["min"]),
              _p(_signed(p["plus_minus"]), 7.4, _col(p["plus_minus"]), bold=True,
                 align=TA_RIGHT)] for p in li["pairs"]]
    trows = [[" + ".join(p["players"]), str(p["min"]),
              _p(_signed(p["plus_minus"]), 7.4, _col(p["plus_minus"]), bold=True,
                 align=TA_RIGHT)] for p in li["trios"]]
    right = [_p("Parejas · 8+ min", 10.5, NAVY, bold=True), Spacer(1, 2 * mm),
             _table(["PAREJA", "MIN", "+/-"], prows or [["—"] * 3],
                    [half * 0.58, half * 0.2, half * 0.2], aligns=[None, "R", "R"], size=7),
             Spacer(1, 3 * mm),
             _p("Tríos · 6+ min", 10.5, NAVY, bold=True), Spacer(1, 2 * mm),
             _table(["TRÍO", "MIN", "+/-"], trows or [["—"] * 3],
                    [half * 0.58, half * 0.2, half * 0.2], aligns=[None, "R", "R"], size=7)]

    body = Table([[Table([[f] for f in left], colWidths=[half]), "",
                   Table([[f] for f in right], colWidths=[half])]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 4 * mm))
    top_min = li["units"][0]["min"] if li["units"] else "—"
    S.append(_note(
        f"<b>Qué NO concluir:</b> los quintetos están validados contra los minutos y el "
        f"+/- oficiales, pero ninguno pasa de {top_min} minutos. Con esas muestras son "
        f"índices para elegir vídeo, no veredictos. Las parejas y los tríos acumulan más "
        f"minutos, así que dan algo más de señal.", accent=BAD,
        bg=colors.HexColor("#FBE3E0")))


# ---------------------------------------------------------------- 13 claves
def _keys_page(S, rep, sec):
    sec("Claves de scouting")
    S.append(_title("Claves para preparar a cada equipo"))
    S.append(Spacer(1, 3 * mm))
    half = (CONTENT_W - 5 * mm) / 2
    panels = []
    for side in ("home", "away"):
        k = rep["keys"][side]
        body = [
            _p(f"<b>Qué quitarle:</b> {'; '.join(k['take_away'])}.", 8.4, INK, leading=11.5),
            Spacer(1, 2.5 * mm),
            _p(f"<b>Dónde atacarle:</b> {'; '.join(k['attack'])}.", 8.4, INK, leading=11.5),
            Spacer(1, 2.5 * mm),
            _p(f"<b>A vigilar:</b> {'; '.join(k['watch'])}.", 8.4, INK, leading=11.5),
        ]
        panels.append(_panel(k["team"], body, half,
                             accent=ACCENT if side == "home" else WOOD))
    body = Table([[panels[0], "", panels[1]]], colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 5 * mm))
    S.append(_note("Las claves salen de los números de ESTE partido. Antes de llevarlas a "
                   "la pizarra conviene contrastarlas con el informe de temporada del "
                   "equipo: un partido puede ser una excepción.", accent=BLUE, bg=BLUE_SOFT))


# ---------------------------------------------------------------- 14 calidad
def _quality_page(S, rep, sec):
    sec("Calidad del dato y metodología")
    q = rep["quality"]
    S.append(_title("Qué podemos afirmar y qué sería falsamente preciso"))
    S.append(Spacer(1, 3 * mm))
    half = (CONTENT_W - 5 * mm) / 2
    ver = []
    for v in q["verified"]:
        ver.append(_p(f"· {v}", 8.2, INK, leading=11))
        ver.append(Spacer(1, 1.2 * mm))
    est = []
    for v in q["estimated"]:
        est.append(_p(f"· {v}", 8.2, INK, leading=11))
        est.append(Spacer(1, 1.2 * mm))
    body = Table([[_panel("Verificado / reconciliado", ver or [_p("—", 8)], half, accent=GOOD),
                   "", _panel("Estimado o limitado", est or [_p("—", 8)], half, accent=BAD)]],
                 colWidths=[half, 5 * mm, half])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    S.append(body)
    S.append(Spacer(1, 5 * mm))

    S.append(_p(f"Nivel de dato: {q['level']}", 10.5, NAVY, bold=True))
    S.append(Spacer(1, 2 * mm))
    defs = [
        ("Posesión real", "Serie de acciones ofensivas de un equipo (tiro, tiro libre, "
                          "pérdida, rebote ofensivo) que termina cuando el balón cambia de manos."),
        ("2ª oportunidad · tras pérdida · rápidos",
         "Puntos tras rebote ofensivo · en posesiones iniciadas por pérdida rival · "
         "en los primeros 8 s tras robo, rebote defensivo o pérdida."),
        ("eFG% · TS% · FTr · TOV% · ORB%",
         "(TC+0,5·T3)/TCI · PTS/[2·(TCI+0,44·TLI)] · TLI/TCI · pérdidas/posesiones reales · "
         "rebotes ofensivos/(propios + defensivos del rival)."),
        ("Game Score", "PTS + 0,4·TC − 0,7·TCI − 0,4·(TLI−TL) + 0,7·RO + 0,3·RD + ROB "
                       "+ 0,7·AS + 0,7·TAP − 0,4·FC − PÉR."),
        ("Oliver", "Pts producidos, Floor%, Stops y eficiencias individuales: "
                   "<i>Basketball on Paper</i>, implementación oliver_bref_v1."),
        ("Zonas de tiro", f"Geometría FIBA sobre las coordenadas de la FEB, calibrada "
                          f"contra el valor real de cada tiro ({COURT_L} m de fondo y "
                          f"{COURT_W} m de ancho por lienzo)."),
    ]
    for label, text in defs:
        S.append(_p(f"<b>{label}</b>", 7.8, NAVY))
        S.append(_p(text, 7.4, MUTED, leading=9.5))
        S.append(Spacer(1, 1.6 * mm))

    S.append(Spacer(1, 3 * mm))
    t = Table([[_p("Criterio PiScouting", 10.5, ACCENT, bold=True)],
               [_p("Dato oficial, cálculo derivado y reconstrucción van separados. Lo "
                   "validable se valida, lo estimado se etiqueta y lo que el feed no "
                   "permite calcular se omite en vez de rellenarse.", 8.4,
                   colors.HexColor("#DDE3EC"), leading=11.5)]],
              colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1B2436")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
    ]))
    S.append(t)
