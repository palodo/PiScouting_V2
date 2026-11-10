"""Informe post-partido en PDF.

Estética de retransmisión: fondo casi negro, numerales grandes y naranja de marca como
único color caliente. Deliberadamente NO sigue el blanco editorial del informe de
temporada (`pdf_report.py`): este se mira en pantalla y en el móvil camino del pabellón,
y ahí el fondo oscuro manda. Si alguna vez hay que tirarlo a papel, lo suyo es una
variante clara aparte, no retocar esta.

Dos reglas de la paleta, que son lo que hace que el informe se lea de un vistazo:

  · **Cada equipo tiene SU color** en todo el documento: el local va en naranja y el
    visitante en cian. Barras, gráfico de evolución, mapas de tiro y tablas usan siempre
    el mismo, así que no hay que volver a la leyenda en cada página.
  · **El color no se gasta en adornos.** Si algo va en naranja o cian es porque es un
    dato; los marcos y las separaciones van en gris.

Secciones (una por página):
   portada · resumen ejecutivo · evolución del marcador · fases y tiempos muertos ·
   estadística avanzada · economía de posesión · perfil de tiro · impacto y banquillo ·
   boxscore de cada equipo · producción individual · rotaciones · claves · calidad del dato

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
    PageBreak, Image as RLImage, NextPageTemplate,
)
from sqlmodel import Session

from . import postgame
from .postgame import COURT_L, COURT_W, HOOP_D, THREE_R, CORNER_Y, CORNER_D

# ------------------------------ paleta ------------------------------
INK = colors.HexColor("#0B0F1A")          # fondo de página
PANEL = colors.HexColor("#141B2B")        # tarjetas y tablas
PANEL_2 = colors.HexColor("#1B2437")      # fila alterna / pista
HAIR = colors.HexColor("#283449")         # filetes
HAIR_SOFT = colors.HexColor("#1F2938")
TEXT = colors.HexColor("#EDF1F8")
DIM = colors.HexColor("#8694AE")
GHOST = colors.HexColor("#202B40")        # carriles de barras y fila de totales
PAGE_GHOST = colors.HexColor("#161E2E")   # numeral de página: casi fondo, solo textura

HOME = colors.HexColor("#FF5A1F")         # naranja de marca: equipo local
AWAY = colors.HexColor("#1FD4C3")         # cian: equipo visitante
GOLD = colors.HexColor("#FFC24A")
GOOD = colors.HexColor("#3DDC84")
BAD = colors.HexColor("#FF5470")

PW, PH = A4
MARGIN = 14 * mm
CONTENT_W = PW - 2 * MARGIN

_styles = getSampleStyleSheet()

# En español el separador decimal es la coma. Se aplica al pintar; la API sigue
# devolviendo números de verdad (0.61), que es lo que quiere quien los consume.
# Ojo: solo FUERA de las etiquetas, o un `size=6.4` del marcado se convertiría en
# `size=6,4` y ReportLab no sabe leer eso.
_DEC = re.compile(r"(?<=\d)\.(?=\d)")
_CHUNK = re.compile(r"<[^>]*>|[^<]+")


def _es(text: str) -> str:
    return "".join(c if c.startswith("<") else _DEC.sub(",", c)
                   for c in _CHUNK.findall(str(text)))


def _hex(c: colors.Color) -> str:
    return "#" + c.hexval()[2:]


def _p(text, size=9, color=TEXT, bold=False, align=TA_LEFT, leading=None, font=None):
    return Paragraph(_es(text), ParagraphStyle(
        "x", parent=_styles["Normal"], fontSize=size,
        fontName=font or ("Helvetica-Bold" if bold else "Helvetica"),
        textColor=color, alignment=align, leading=leading or size + 3))


def _lbl(text, size=6.5, color=DIM, align=TA_LEFT):
    """Etiqueta pequeña en mayúsculas: lo que ordena toda la retícula del informe."""
    return _p(str(text).upper(), size, color, bold=True, leading=size + 2, align=align)


def _signed(v) -> str:
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return "—"
    return f"+{v}" if v > 0 else str(v)


def _col(v) -> colors.Color:
    try:
        return GOOD if float(v) > 0 else (BAD if float(v) < 0 else DIM)
    except (TypeError, ValueError):
        return DIM


def _na(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def _clip(text, n=26) -> str:
    text = str(text)
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


# Palabras que no distinguen a un equipo de otro: lo que de verdad lo identifica suele ir
# detrás del patrocinador ("CMG HIDRÁULICA NB TORRENT" -> "NB TORRENT").
_FILLER = {"CB", "CD", "CLUB", "BALONCESTO", "BASKET", "BASQUET", "BÀSQUET", "DE", "DEL",
           "LA", "EL", "SAD", "SD", "UD", "CE", "AB", "BC"}


def _abbr(name: Optional[str], n: int = 14) -> str:
    """Nombre de equipo corto para cabeceras, barras y tablas estrechas."""
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
    # una sola palabra que se pasa por poco se deja entera
    return out if len(out) <= n + 3 else out[:n - 1].rstrip() + "…"


# ============================ bloques ============================
def _stack(rows, width):
    """Apila flowables en una columna de ancho fijo, sin márgenes."""
    t = Table([[f] for f in rows], colWidths=[width])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _box(rows, width=None, bg=PANEL, accent=None, pad=9):
    """Tarjeta oscura con filete. `accent` pinta una barra de color arriba."""
    t = Table([[f] for f in rows], colWidths=[width] if width else None)
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.6, HAIR),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if accent is not None:
        style.append(("LINEABOVE", (0, 0), (-1, 0), 2.4, accent))
    t.setStyle(TableStyle(style))
    return t


def _card(value, label, foot="", accent=HOME, w=None):
    """Tarjeta de dato: barra de color arriba, etiqueta y el número a gran tamaño."""
    value = str(value)
    size = 21 if len(value) <= 6 else (17 if len(value) <= 9 else 13)
    rows = [_lbl(_clip(label, 24), 6.2),
            _p(value, size, TEXT, bold=True, leading=size + 2)]
    heights = [10, size + 5]
    if foot:
        rows.append(_p(_clip(foot, 44), 6.3, DIM, leading=7.6))
        heights.append(15)
    t = Table([[f] for f in rows], colWidths=[w] if w else None, rowHeights=heights)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEABOVE", (0, 0), (-1, 0), 2.2, accent),
        ("BOX", (0, 0), (-1, -1), 0.6, HAIR),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _cols(items, width=None, gap=4 * mm):
    """Coloca N bloques en una fila con separación, repartiendo el ancho."""
    width = width or CONTENT_W
    n = len(items)
    if not n:
        return Spacer(1, 1)
    cw = (width - gap * (n - 1)) / n
    cells, widths = [], []
    for i, c in enumerate(items):
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


def _row_of(cards, gap=3.5 * mm, width=None):
    return _cols(cards, width=width, gap=gap)


def _panel(title, body, width, accent=HOME):
    return _box([_lbl(title, 7.4, accent), Spacer(1, 2.2 * mm)] + list(body), width)


def _titled(title, body, width, accent=HOME):
    """Igual que un panel pero sin caja: el título flota sobre el bloque."""
    return _stack([_lbl(title, 7.4, accent), Spacer(1, 2.2 * mm)] + list(body), width)


def _note(text, width=None, accent=HOME):
    t = Table([[_p(text, 8, DIM, leading=11)]], colWidths=[width or CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _table(head: list, rows: list[list], widths: list, aligns=None, size=7.6,
           zebra=True, bold_first=False, accent=HOME):
    data = [[_lbl(h, 6.2, DIM, align=TA_RIGHT if (aligns and aligns[i] == "R") else TA_LEFT)
             for i, h in enumerate(head)]]
    for r in rows:
        line = []
        for i, cell in enumerate(r):
            if isinstance(cell, (Paragraph, Table)):
                line.append(cell)
            else:
                line.append(_p(cell, size, TEXT, bold=(bold_first and i == 0),
                               align=TA_RIGHT if (aligns and aligns[i] == "R") else TA_LEFT))
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, accent),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, HAIR_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, HAIR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), PANEL_2))
    t.setStyle(TableStyle(style))
    return t


def _bar(label, value, maxv, width, color=HOME, suffix="%", label_w=0.24):
    """Barra sobre carril oscuro, con el valor al final."""
    frac = max(0.0, min(1.0, (value or 0) / maxv if maxv else 0))
    track_w = max(10.0, width * (1 - label_w - 0.2))
    filled = max(1.0, track_w * frac)
    bar = Table([[""]], colWidths=[filled], rowHeights=[6])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    track = Table([[bar, ""]], colWidths=[filled, max(0.1, track_w - filled)],
                  rowHeights=[6])
    track.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), GHOST),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    t = Table([[_p(label, 7, DIM), track,
                _p(f"{value}{suffix}", 8.4, TEXT, bold=True, align=TA_RIGHT)]],
              colWidths=[width * label_w, track_w, width * 0.2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _versus(label, a, b, width, suffix="", maxv=None):
    """Una métrica enfrentada: dos barras que nacen del centro, local a la izquierda y
    visitante a la derecha. Se ve quién gana sin leer los números."""
    hi = maxv or max(abs(a or 0), abs(b or 0), 1)
    half = width * 0.3
    la = max(1.0, half * min(1.0, abs(a or 0) / hi))
    lb = max(1.0, half * min(1.0, abs(b or 0) / hi))
    left = Table([["", ""]], colWidths=[half - la, la], rowHeights=[7])
    left.setStyle(TableStyle([("BACKGROUND", (1, 0), (1, 0), HOME),
                              ("BACKGROUND", (0, 0), (0, 0), GHOST),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    right = Table([["", ""]], colWidths=[lb, half - lb], rowHeights=[7])
    right.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), AWAY),
                               ("BACKGROUND", (1, 0), (1, 0), GHOST),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    t = Table([[_p(f"{a}{suffix}", 9, TEXT, bold=True, align=TA_RIGHT), left,
                _lbl(label, 6.6, DIM, align=TA_CENTER), right,
                _p(f"{b}{suffix}", 9, TEXT, bold=True)]],
              colWidths=[width * 0.11, half, width * 0.18, half, width * 0.11])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


# ============================ gráficos ============================
_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
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


def _rgb(c) -> tuple[int, int, int]:
    if isinstance(c, colors.Color):
        return (int(c.red * 255), int(c.green * 255), int(c.blue * 255))
    return c


def _mix(a, b, t: float) -> tuple[int, int, int]:
    """Mezcla dos colores. PIL no maneja alfa sobre RGB, así que las transparencias
    del informe son mezclas calculadas contra el fondo."""
    ra, rb = _rgb(a), _rgb(b)
    return tuple(int(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


def render_flow(flow: dict, home: str, away: str, w=1600, h=470) -> io.BytesIO:
    """Diferencia de marcador. Naranja cuando manda el local, cian cuando el visitante."""
    bg = _rgb(PANEL)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    pad_l, pad_r, pad_t, pad_b = 80, 26, 34, 50
    f_axis, f_lab = _font(21), _font(26)
    series = flow["series"] or [{"t": 0, "diff": 0}]
    end = max(s["t"] for s in series) or 2400
    top = max(12, max(abs(s["diff"]) for s in series) + 3)

    def X(t):
        return pad_l + (t / end) * (w - pad_l - pad_r)

    def Y(v):
        return pad_t + (top - v) / (2 * top) * (h - pad_t - pad_b)

    for v in (top, top / 2, 0, -top / 2, -top):
        d.line([pad_l, Y(v), w - pad_r, Y(v)], fill=_rgb(HAIR_SOFT), width=1)
        d.text((16, Y(v) - 12), f"{int(v):+d}" if v else "0", fill=_rgb(DIM), font=f_axis)

    q = 600
    while q < end:
        d.line([X(q), pad_t, X(q), h - pad_b], fill=_rgb(HAIR), width=2)
        q += 600

    base = Y(0)
    pts = [(X(s["t"]), Y(s["diff"])) for s in series]
    up = _mix(bg, HOME, 0.32)
    dn = _mix(bg, AWAY, 0.28)
    for (x0, y0), (x1, _) in zip(pts, pts[1:]):
        if abs(y0 - base) < 0.5:
            continue
        d.rectangle([x0, min(y0, base), max(x1, x0 + 1), max(y0, base)],
                    fill=up if y0 < base else dn)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        col = _rgb(HOME) if y0 <= base else _rgb(AWAY)
        d.line([x0, y0, x1, y0], fill=col, width=4)   # escalera: el marcador salta
        d.line([x1, y0, x1, y1], fill=col, width=4)
    d.line([pad_l, base, w - pad_r, base], fill=_rgb(DIM), width=2)

    labels = ["Q1", "Q2", "Q3", "Q4", "PR1", "PR2"]
    i, q = 0, 0
    while q < end and i < len(labels):
        d.text(((X(q) + X(min(q + 600, end))) / 2 - 16, h - pad_b + 14), labels[i],
               fill=_rgb(DIM), font=f_axis)
        q += 600
        i += 1
    d.text((pad_l + 12, pad_t + 4), home.upper(), fill=_rgb(HOME), font=f_lab)
    d.text((pad_l + 12, h - pad_b - 36), away.upper(), fill=_rgb(AWAY), font=f_lab)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def render_court(shots: list[dict], color, w=640, scale=2) -> io.BytesIO:
    """Media pista oscura. Anotado = color del equipo con halo; fallado = aro apagado.

    La pista se dibuja con la MISMA geometría con la que se clasifican las zonas
    (`postgame.COURT_L/COURT_W`), así que un tiro cae donde dice la tabla de zonas.
    """
    W = int(w * scale)
    H = int(W * COURT_L / COURT_W)
    M = W / COURT_W                       # píxeles por metro
    bg = _rgb(PANEL_2)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    line = _mix(bg, DIM, 0.55)
    lw = max(2, int(1.5 * scale))

    def PX(dy):
        return W / 2 + dy * M

    def PY(depth):
        return H - depth * M

    d.rectangle([PX(-7.5), PY(COURT_L), PX(7.5), PY(0)], outline=line, width=lw)
    d.rectangle([PX(-2.45), PY(5.8), PX(2.45), PY(0)], outline=line, width=lw)
    r = 1.80 * M
    d.arc([PX(-1.8), PY(5.8) - r, PX(1.8), PY(5.8) + r], 180, 360, fill=line, width=lw)
    d.line([PX(-0.9), PY(1.2), PX(0.9), PY(1.2)], fill=line, width=lw + 1)
    rr = 0.225 * M
    d.ellipse([PX(0) - rr, PY(HOOP_D) - rr, PX(0) + rr, PY(HOOP_D) + rr],
              outline=line, width=lw)
    d.line([PX(-CORNER_Y), PY(0), PX(-CORNER_Y), PY(CORNER_D)], fill=line, width=lw)
    d.line([PX(CORNER_Y), PY(0), PX(CORNER_Y), PY(CORNER_D)], fill=line, width=lw)
    R = THREE_R * M
    d.arc([PX(0) - R, PY(HOOP_D) - R, PX(0) + R, PY(HOOP_D) + R], 180, 360,
          fill=line, width=lw)

    miss = _mix(bg, DIM, 0.68)
    hot = _rgb(color)
    halo = _mix(bg, hot, 0.38)
    for s in shots:
        depth, dy = postgame.court_metres(s["hx"], s["hy"])
        x, y = PX(dy), PY(depth)
        if s["made"]:
            g = 9 * scale
            d.ellipse([x - g, y - g, x + g, y + g], fill=halo)
            k = 4.6 * scale
            d.ellipse([x - k, y - k, x + k, y + k], fill=hot)
        else:
            k = 4.2 * scale
            d.ellipse([x - k, y - k, x + k, y + k], outline=miss, width=max(2, scale))

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
        buf, pagesize=A4, topMargin=24 * mm, bottomMargin=13 * mm,
        leftMargin=MARGIN, rightMargin=MARGIN,
        title=f"Informe {mt['home']['name']} vs {mt['away']['name']}",
        author="PiScouting")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="cover",
                     frames=[Frame(0, 0, PW, PH, leftPadding=0, rightPadding=0,
                                   topPadding=0, bottomPadding=0)],
                     onPage=lambda c, d: _cover_bg(c, d, rep)),
        PageTemplate(id="main", frames=[frame],
                     onPage=lambda c, d: _page_furniture(c, d, rep)),
    ])

    S: list = []
    _cover(S, rep)
    # La portada tiene su propia plantilla (sin márgenes). Sin esto, ReportLab la
    # mantendría en TODO el documento.
    S.append(NextPageTemplate("main"))
    n = [0]

    def sec(kicker, title, sub=""):
        n[0] += 1
        S.append(PageBreak())
        S.append(_section_head(n[0], kicker, title, sub))

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


def _section_head(n: int, kicker: str, title: str, sub: str = ""):
    """Cabecera de sección: el número a gran tamaño en naranja y el título al lado."""
    right = [_lbl(kicker, 6.6, DIM), _p(title, 19, TEXT, bold=True, leading=22)]
    if sub:
        right.append(Spacer(1, 1.6 * mm))
        right.append(_p(sub, 8, DIM, leading=10.6))
    t = Table([[_p(f"{n:02d}", 29, HOME, bold=True, align=TA_RIGHT, leading=29),
                _stack(right, CONTENT_W - 21 * mm)]],
              colWidths=[15 * mm, CONTENT_W - 15 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEAFTER", (0, 0), (0, 0), 1.2, HOME),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 6), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return _stack([t, Spacer(1, 5 * mm)], CONTENT_W)


# ---------------------------------------------------------------- portada
def _draw_arc_watermark(canvas, cx, cy, scale, color, width=1.2):
    """La línea de 6,75 con sus dos rectas de esquina, a tamaño grande y en filete fino.

    Es la marca de agua de la portada. Se dibuja SOLO el arco (ni zona ni perímetro):
    una media pista entera recortada por el borde del papel parece un error de montaje;
    el arco suelto se lee como lo que es, un gesto gráfico.
    """
    M = scale
    canvas.saveState()
    canvas.setStrokeColor(color)
    canvas.setLineWidth(width)
    canvas.setLineCap(1)

    def PX(dy):
        return cx + dy * M

    def PY(depth):
        return cy + depth * M

    canvas.line(PX(-CORNER_Y), PY(0), PX(-CORNER_Y), PY(CORNER_D))
    canvas.line(PX(CORNER_Y), PY(0), PX(CORNER_Y), PY(CORNER_D))
    path = canvas.beginPath()
    steps = 96
    a0 = math.atan2(CORNER_D - HOOP_D, -CORNER_Y)      # donde el arco corta la recta
    for i in range(steps + 1):
        a = a0 + (math.pi - 2 * a0) * i / steps
        x, y = PX(THREE_R * math.cos(a)), PY(HOOP_D + THREE_R * math.sin(a))
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    canvas.drawPath(path, stroke=1, fill=0)
    canvas.restoreState()


def _cover_bg(canvas, doc, rep):
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, 0, PW, PH, fill=1, stroke=0)
    # la línea de 6,75 a sangre por abajo, como marca de agua
    _draw_arc_watermark(canvas, PW / 2, -40 * mm, 13.5 * mm,
                        colors.HexColor("#1A2434"), width=1.6)
    canvas.setFillColor(colors.HexColor("#4E5A72"))
    canvas.setFont("Helvetica", 6.6)
    canvas.drawString(MARGIN, 11 * mm,
                      "RESULTADO OFICIAL Y PLAY-BY-PLAY RECONCILIADOS · "
                      "LAS MÉTRICAS ESTIMADAS SE IDENTIFICAN COMO TALES")
    canvas.restoreState()


def _cover(S, rep):
    mt = rep["match"]
    h, a = mt["home"], mt["away"]
    inner = CONTENT_W - 2 * MARGIN

    def band(flow):
        return Table([[flow]], colWidths=[CONTENT_W],
                     style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), MARGIN),
                                       ("RIGHTPADDING", (0, 0), (-1, -1), MARGIN),
                                       ("TOPPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))

    S.append(Spacer(1, 20 * mm))
    S.append(band(Table(
        [[_p(f"PI<font color='{_hex(HOME)}'>SCOUTING</font>", 15, TEXT, bold=True),
          _lbl("Informe post-partido", 7, DIM, align=TA_RIGHT)]],
        colWidths=[inner * 0.5, inner * 0.5],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                          ("LEFTPADDING", (0, 0), (-1, -1), 0),
                          ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))))
    S.append(Spacer(1, 2.5 * mm))
    S.append(band(Table([[""]], colWidths=[inner], rowHeights=[0.9],
                        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), HAIR)]))))
    S.append(Spacer(1, 3 * mm))
    sub = " · ".join(x for x in [mt["competition"], mt.get("grupo"), mt.get("jornada")] if x)
    S.append(band(_lbl(sub, 7, DIM)))
    S.append(Spacer(1, 20 * mm))

    # --- marcador: una fila por equipo, el ganador en su color ---
    def team_row(team, color, won, role):
        name = team["name"].upper()
        name_f = _p(name, 17 if len(name) < 24 else 13, TEXT if won else DIM,
                    bold=True, leading=19)
        score = _p(str(team["score"]), 44,
                   color if won else colors.HexColor("#56627C"),
                   bold=True, align=TA_RIGHT, leading=44)
        t = Table([[_stack([name_f, _lbl(role, 6.2, DIM)], inner * 0.66 - 12), score]],
                  colWidths=[inner * 0.66, inner * 0.34])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), PANEL if won else INK),
            ("LINEBEFORE", (0, 0), (0, 0), 3.4, color if won else HAIR),
            ("LEFTPADDING", (0, 0), (0, 0), 10), ("LEFTPADDING", (1, 0), (1, 0), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    win_h = mt["winner"] == "home"
    S.append(band(team_row(h, HOME, win_h, "Local")))
    S.append(Spacer(1, 2.5 * mm))
    S.append(band(team_row(a, AWAY, not win_h, "Visitante")))
    S.append(Spacer(1, 7 * mm))

    # --- parciales por cuarto, en fichas ---
    chips = []
    for q in mt["quarters"]:
        hv, av = q.get("home") or 0, q.get("away") or 0
        chips.append(Table(
            [[_lbl(f"Q{q['n']}", 6, DIM, align=TA_CENTER)],
             [_p(f"<font color='{_hex(HOME if hv >= av else DIM)}'>{hv}</font>"
                 f"<font color='{_hex(DIM)}'>–</font>"
                 f"<font color='{_hex(AWAY if av > hv else DIM)}'>{av}</font>",
                 12, TEXT, bold=True, align=TA_CENTER)]],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL),
                              ("BOX", (0, 0), (-1, -1), 0.6, HAIR),
                              ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])))
    if mt.get("halftime"):
        chips.append(Table(
            [[_lbl("Descanso", 6, DIM, align=TA_CENTER)],
             [_p(mt["halftime"].replace("-", "–"), 12, TEXT, bold=True, align=TA_CENTER)]],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL),
                              ("BOX", (0, 0), (-1, -1), 0.6, HAIR),
                              ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])))
    S.append(band(_cols(chips, width=inner, gap=2.5 * mm)))
    S.append(Spacer(1, 13 * mm))

    S.append(band(_p(rep["summary"]["headline"], 22, TEXT, bold=True, leading=26)))
    S.append(Spacer(1, 4 * mm))
    S.append(band(_p(rep["summary"]["lead"], 9, DIM, leading=13)))
    S.append(Spacer(1, 15 * mm))

    fecha = mt.get("date") or "—"
    if fecha != "—":
        y, mo, dd = fecha.split("-")
        fecha = f"{dd}/{mo}/{y}"
    meta = [("Fecha", fecha), ("Pabellón", _clip(mt.get("venue") or "—", 30)),
            ("Nivel de dato", rep["quality"]["level"].capitalize())]
    cells = [_stack([Table([[""]], colWidths=[inner / 3 - 4 * mm], rowHeights=[1.4],
                           style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), HOME)])),
                     Spacer(1, 2 * mm), _lbl(k, 6, DIM),
                     _p(v, 8.4, TEXT, bold=True, leading=10)], inner / 3 - 4 * mm)
             for k, v in meta]
    S.append(band(_cols(cells, width=inner, gap=6 * mm)))


def _page_furniture(canvas, doc, rep):
    mt = rep["match"]
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, 0, PW, PH, fill=1, stroke=0)

    # numeral fantasma de página: da profundidad sin molestar
    canvas.setFillColor(PAGE_GHOST)
    canvas.setFont("Helvetica-Bold", 44)
    canvas.drawRightString(PW - MARGIN, PH - 21 * mm, f"{doc.page:02d}")

    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 7.4)
    canvas.drawString(MARGIN, PH - 13 * mm,
                      f"{_abbr(mt['home']['name'], 22)}  {mt['home']['score']}"
                      f"–{mt['away']['score']}  {_abbr(mt['away']['name'], 22)}")
    canvas.setFillColor(DIM)
    canvas.setFont("Helvetica", 6.6)
    extra = " · ".join(x for x in [mt["competition"], mt.get("grupo"),
                                   (mt.get("date") or "")] if x)
    canvas.drawString(MARGIN, PH - 16.4 * mm, extra[:110])
    canvas.setStrokeColor(HAIR)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, PH - 18.6 * mm, PW - MARGIN, PH - 18.6 * mm)

    canvas.setFillColor(colors.HexColor("#4E5A72"))
    canvas.setFont("Helvetica", 6.2)
    canvas.drawString(MARGIN, 8.5 * mm, "PISCOUTING · ANÁLISIS DE BALONCESTO FEB")
    canvas.drawRightString(PW - MARGIN, 8.5 * mm,
                           "FUENTE: FEB LIVESTATS · MÉTRICAS E INTERPRETACIÓN PISCOUTING")
    canvas.restoreState()


# ---------------------------------------------------------------- 01 resumen
def _summary_page(S, rep, sec):
    sm = rep["summary"]
    sec("Resumen ejecutivo", sm["headline"])
    S.append(_note(sm["lead"]))
    S.append(Spacer(1, 4 * mm))
    accents = [HOME, HOME, AWAY, GOLD, AWAY, GOLD]
    S.append(_row_of([_card(c["value"], c["label"], c["foot"], accent=accents[i % len(accents)])
                      for i, c in enumerate(sm["cards"][:5])]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 4 * mm) / 2
    left, right = [], []
    for d in sm["decided"]:
        left.append(_p(f"<b>{d['title']}.</b> {d['text']}", 8.4, TEXT, leading=11.6))
        left.append(Spacer(1, 2.4 * mm))
    for g in sm["signals"]:
        right.append(_p(f"<b>{g['title']}:</b> {g['text']}", 8.4, TEXT, leading=11.6))
        right.append(Spacer(1, 2.4 * mm))
    S.append(_cols([_panel("Qué decidió el partido", left or [_p("—", 8, DIM)], half),
                    _panel("Señales de juego", right or [_p("—", 8, DIM)], half,
                           accent=AWAY)]))
    S.append(Spacer(1, 5 * mm))
    k = rep["keys"]
    S.append(_note(
        f"<b>Para preparar a los dos:</b> a {k['home']['team']} hay que quitarle "
        f"{k['home']['take_away'][0]}; a {k['away']['team']}, {k['away']['take_away'][0]}.",
        accent=GOLD))


# ---------------------------------------------------------------- 02 evolución
def _flow_page(S, rep, sec):
    fl, mt = rep["flow"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    lt = fl["lead_time"]
    leader, label = (hn, lt["home_label"]) if lt["home"] >= lt["away"] else (an, lt["away_label"])
    sec("Evolución del marcador", f"{leader} mandó {label} de los 40 minutos")

    S.append(RLImage(render_flow(fl, _abbr(hn, 24), _abbr(an, 24)),
                     width=CONTENT_W, height=CONTENT_W * 470 / 1600))
    S.append(Spacer(1, 4 * mm))
    home_dry = fl["droughts"]["home"]["seconds"] >= fl["droughts"]["away"]["seconds"]
    big = fl["droughts"]["home"] if home_dry else fl["droughts"]["away"]
    S.append(_row_of([
        _card(lt["home_label"], f"{_abbr(hn, 16)} por delante",
              f"máx. +{fl['max_lead']['home']['pts']} · {fl['max_lead']['home']['at']}",
              accent=HOME),
        _card(lt["away_label"], f"{_abbr(an, 16)} por delante",
              f"máx. +{fl['max_lead']['away']['pts']} · {fl['max_lead']['away']['at']}",
              accent=AWAY),
        _card(str(fl["lead_changes"]), "Cambios de líder", f"{fl['ties']} empate(s)",
              accent=GOLD),
        _card(big["label"], "Sequía más larga",
              f"{_abbr(hn if home_dry else an)} · {big['from']}", accent=BAD),
    ]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 4 * mm) / 2
    rows = []
    for r in fl["runs"]:
        col = HOME if r["is_home"] else AWAY
        rows.append([_p(_abbr(hn if r["is_home"] else an), 7.6, col, bold=True),
                     _p(r["run"], 8.4, TEXT, bold=True),
                     f"{r['from_score']} → {r['to_score']}",
                     _p(f"{r['from_clock']} → {r['to_clock']}", 7, DIM)])
    left = [_table(["Equipo", "Parcial", "Marcador", "Reloj"], rows or [["—"] * 4],
                   [half * 0.3, half * 0.13, half * 0.28, half * 0.29], size=7.2),
            Spacer(1, 1.6 * mm),
            _p("Marcador oficial local-visitante, tomado justo antes de la primera "
               "canasta de la racha.", 6.6, DIM, leading=8.4)]

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
        right.append(_p(t, 8.4, TEXT, leading=11.6))
        right.append(Spacer(1, 2.4 * mm))

    S.append(_cols([_titled("Rachas sin respuesta · 6+ puntos", left, half),
                    _panel("Qué significa", right, half, accent=AWAY)]))


# ---------------------------------------------------------------- 03 fases
def _phases_page(S, rep, sec):
    ph, mt = rep["phases"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    best = max(ph["quarters"], key=lambda q: abs(q["open3_diff"]), default=None)
    title = "Arranques, tramos centrales y cierres"
    if best and abs(best["open3_diff"]) >= 5:
        who = hn if best["open3_diff"] > 0 else an
        title = f"{who} ganó el arranque del Q{best['quarter']} por {best['open3']}"
    sec("Fases de cada cuarto", title, f"Parciales expresados {hn} – {an}.")

    def cell(txt, diff):
        return _p(f'{txt} <font color="{_hex(_col(diff))}">({_signed(diff)})</font>',
                  7.8, TEXT)

    rows = []
    for q in ph["quarters"]:
        rows.append([_p(f"Q{q['quarter']}", 8.4, HOME, bold=True),
                     cell(q["open3"], q["open3_diff"]), cell(q["mid"], q["mid_diff"]),
                     cell(q["close2"], q["close2_diff"]),
                     _p(q["total"], 9, TEXT, bold=True, align=TA_RIGHT)])
    w = CONTENT_W
    S.append(_table(["Periodo", "Primeros 3 min", "Tramo central", "Últimos 2 min", "Cuarto"],
                    rows, [w * 0.13, w * 0.22, w * 0.22, w * 0.22, w * 0.21],
                    aligns=[None, None, None, None, "R"]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 4 * mm) / 2
    trows = []
    for t in ph["timeouts"]:
        col = HOME if t["is_home"] else AWAY
        trows.append([_p(_abbr(hn if t["is_home"] else an, 12), 7.4, col, bold=True),
                      _p(t["at"], 7.2, DIM), t["score"], t["before"], t["after"],
                      _p(_signed(t["swing"]), 7.8, _col(t["swing"]), bold=True,
                         align=TA_RIGHT)])
    left = [_table(["Pide", "Reloj", "Marca.", "2' antes", "2' desp.", "Saldo"],
                   trows or [["—"] * 6],
                   [half * 0.21, half * 0.16, half * 0.19, half * 0.14, half * 0.16,
                    half * 0.14],
                   aligns=[None, None, "R", "R", "R", "R"], size=7.2),
            Spacer(1, 1.6 * mm),
            _p("Parciales desde el punto de vista de quien pide el tiempo muerto. "
               "Muestra pequeña: lectura descriptiva.", 6.6, DIM, leading=8.4)]

    op = ph["quarters"]
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
        ht = [t for t in tos if t["is_home"]]
        at = [t for t in tos if not t["is_home"]]
        txt.append(f"{hn} pidió {len(ht)} tiempo(s) muerto(s) y {an}, {len(at)}. "
                   f"El saldo medio de los 2 minutos siguientes fue "
                   f"{_signed(sum(t['swing'] for t in ht) / len(ht)) if ht else '—'} y "
                   f"{_signed(sum(t['swing'] for t in at) / len(at)) if at else '—'}.")
    right = []
    for t in txt:
        right.append(_p(t, 8.4, TEXT, leading=11.6))
        right.append(Spacer(1, 2.4 * mm))

    S.append(_cols([_titled("Tiempos muertos · 2 min antes y después", left, half),
                    _panel("Lectura", right, half, accent=AWAY)]))


# ---------------------------------------------------------------- 04 avanzada
def _advanced_page(S, rep, sec):
    adv, mt = rep["advanced"], rep["match"]
    h, a = adv["home"], adv["away"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    sec("Estadística avanzada", "Quién ganó cada uno de los cuatro factores",
        f"Ritmo del partido: {adv['pace']} posesiones.   "
        f"<font color='{_hex(HOME)}'>■</font> {hn}    "
        f"<font color='{_hex(AWAY)}'>■</font> {an}")

    S.append(_box([
        _versus("eFG%", h["efg"], a["efg"], CONTENT_W - 18, suffix="%", maxv=75),
        _versus("TOV%", h["tov_pct"], a["tov_pct"], CONTENT_W - 18, suffix="%", maxv=35),
        _versus("ORB%", h["orb_pct"], a["orb_pct"], CONTENT_W - 18, suffix="%", maxv=60),
        _versus("FTr", h["ftr"], a["ftr"], CONTENT_W - 18, suffix="%", maxv=65),
    ], CONTENT_W, accent=HOME))
    S.append(Spacer(1, 1.6 * mm))
    S.append(_p("Cuanto más larga la barra, más alto el valor. En TOV% gana quien la "
                "tiene MÁS CORTA: son pérdidas.", 6.6, DIM))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 4 * mm) / 2
    rows = [
        ["Posesiones reales", _na(h["poss_real"]), _na(a["poss_real"])],
        ["Posesiones estimadas", h["poss_est"], a["poss_est"]],
        ["Ef. ofensiva (pts/100)", h["off_rtg"], a["off_rtg"]],
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
    # el que gana cada métrica, en su color
    better_low = {"TOV%", "Ef. defensiva"}
    painted = []
    for label, va, vb in rows:
        ca = cb = TEXT
        try:
            fa = float(str(va).replace("%", "").replace("+", "").replace(",", "."))
            fb = float(str(vb).replace("%", "").replace("+", "").replace(",", "."))
            if fa != fb:
                h_wins = (fa < fb) if label in better_low else (fa > fb)
                ca, cb = (HOME, TEXT) if h_wins else (TEXT, AWAY)
        except ValueError:
            pass
        painted.append([label,
                        _p(va, 7.8, ca, bold=(ca is not TEXT), align=TA_RIGHT),
                        _p(vb, 7.8, cb, bold=(cb is not TEXT), align=TA_RIGHT)])
    tbl = _table(["Métrica", _abbr(hn), _abbr(an)], painted,
                 [half * 0.46, half * 0.27, half * 0.27], aligns=[None, "R", "R"])

    side = [
        _lbl("Volumen de triple · % de los tiros", 6.6, DIM), Spacer(1, 1.4 * mm),
        _bar(_abbr(hn, 12), h["three_rate"], 70, half * 0.88, color=HOME),
        _bar(_abbr(an, 12), a["three_rate"], 70, half * 0.88, color=AWAY),
        Spacer(1, 3.5 * mm),
        _lbl("Canastas asistidas", 6.6, DIM), Spacer(1, 1.4 * mm),
        _bar(_abbr(hn, 12), h["ast_pct"], 100, half * 0.88, color=HOME),
        _bar(_abbr(an, 12), a["ast_pct"], 100, half * 0.88, color=AWAY),
        Spacer(1, 3.5 * mm),
        _lbl("Asistencias por pérdida", 6.6, DIM), Spacer(1, 1.4 * mm),
        _bar(_abbr(hn, 12), h["ast_to"], 3, half * 0.88, color=HOME, suffix=""),
        _bar(_abbr(an, 12), a["ast_to"], 3, half * 0.88, color=AWAY, suffix=""),
        Spacer(1, 3.5 * mm),
        _p(f"Las dos eficiencias se calculan sobre el ritmo del partido "
           f"({adv['pace']} posesiones), que es el mismo para los dos: comparar «puntos "
           f"por 100» con denominadores distintos inventa una diferencia que no existe. "
           f"TOV%, ORB% y FTr van sobre las posesiones propias.", 7.4, DIM, leading=10),
    ]
    S.append(_cols([tbl, _panel("Cómo juegan", side, half, accent=AWAY)]))


# ---------------------------------------------------------------- 05 economía
def _economy_page(S, rep, sec):
    po, mt = rep["possessions"], rep["match"]
    h, a = po["home"], po["away"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    faster = hn if h["fast_break"] > a["fast_break"] else an
    sec("Economía de posesión",
        f"La carrera fue de {faster}" if h["fast_break"] != a["fast_break"]
        else "De dónde salieron los puntos",
        "Posesiones reconstruidas una a una desde el play-by-play, no estimadas.")

    S.append(_row_of([
        _card(f"{h['second_chance']}-{a['second_chance']}", "Pts 2ª oportunidad",
              f"en {h['second_chance_poss']}-{a['second_chance_poss']} posesiones",
              accent=GOLD),
        _card(f"{h['off_turnovers']}-{a['off_turnovers']}", "Pts tras pérdida",
              f"en {h['off_turnovers_poss']}-{a['off_turnovers_poss']} posesiones",
              accent=HOME),
        _card(f"{h['fast_break']}-{a['fast_break']}", "Pts rápidos (hasta 8 s)",
              f"posesión media {h['avg_seconds']}s / {a['avg_seconds']}s", accent=AWAY),
        _card(f"{h['empty']}/{h['poss']}", "Posesiones vacías",
              f"{_abbr(an)}: {a['empty']}/{a['poss']}", accent=BAD),
    ]))
    S.append(Spacer(1, 5 * mm))

    half = (CONTENT_W - 4 * mm) / 2

    def origin_panel(side, name, color):
        body = []
        for o in side["by_origin"]:
            body.append(_p(f"{o['label']}  <font color='{_hex(DIM)}' size=6.4>"
                           f"{o['pts']} pts · {o['poss']} pos.</font>", 7.4, TEXT))
            body.append(_bar("", o["ppp"], 1.6, half * 0.88, color=color, suffix="",
                             label_w=0.02))
            body.append(Spacer(1, 1 * mm))
        body.append(Spacer(1, 1.5 * mm))
        body.append(_p(f"Total: <b>{side['points']} puntos</b> en {side['poss']} "
                       f"posesiones · {side['ppp']} por posesión", 7.2, DIM))
        return _panel(f"{_abbr(name, 24)} · puntos por posesión", body, half, accent=color)

    S.append(_cols([origin_panel(h, hn, HOME), origin_panel(a, an, AWAY)]))
    S.append(Spacer(1, 5 * mm))

    third = (CONTENT_W - 8 * mm) / 3
    best_h = max(h["by_origin"], key=lambda o: o["ppp"])
    best_a = max(a["by_origin"], key=lambda o: o["ppp"])
    S.append(_cols([
        _panel("Segundas oportunidades",
               [_p(f"{hn} sumó <b>{h['second_chance']} puntos</b> en "
                   f"{h['second_chance_poss']} posesiones con rebote ofensivo; {an}, "
                   f"{a['second_chance']} en {a['second_chance_poss']}.", 8, TEXT,
                   leading=11)], third, accent=GOLD),
        _panel("Puntos tras pérdida",
               [_p(f"{hn} anotó {h['off_turnovers']} puntos tras pérdida rival en "
                   f"{h['off_turnovers_poss']} posesiones; {an}, {a['off_turnovers']} en "
                   f"{a['off_turnovers_poss']}.", 8, TEXT, leading=11)], third, accent=HOME),
        _panel("Según el origen",
               [_p(f"Donde mejor rindió {hn}: {best_h['label'].lower()} "
                   f"({best_h['ppp']} pts por posesión). {an}: "
                   f"{best_a['label'].lower()} ({best_a['ppp']}).", 8, TEXT, leading=11)],
               third, accent=AWAY),
    ]))
    S.append(Spacer(1, 4 * mm))
    S.append(_note(
        "<b>Definiciones:</b> segunda oportunidad = puntos tras un rebote ofensivo dentro "
        "de la misma posesión · tras pérdida = posesiones que empiezan por pérdida rival · "
        "rápidos = puntos en los primeros 8 s de una posesión que empieza con robo, rebote "
        "defensivo o pérdida rival.", accent=DIM))


# ---------------------------------------------------------------- 06 tiro
def _shooting_page(S, rep, sec):
    sh, mt = rep["shooting"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    zh = {z["zone"]: z for z in sh["zones"]["home"]}
    za = {z["zone"]: z for z in sh["zones"]["away"]}
    sec("Perfil de tiro", "Dónde tiró cada equipo y qué sacó de cada zona",
        "Círculo lleno = anotado · aro vacío = fallado.")

    half = (CONTENT_W - 4 * mm) / 2
    panels = []
    for side, name, col in (("home", hn, HOME), ("away", an, AWAY)):
        shots = sh["shots"][side]
        made = sum(1 for s in shots if s["made"])
        img = RLImage(render_court(shots, col),
                      width=half * 0.9, height=half * 0.9 * COURT_L / COURT_W)
        panels.append(_panel(f"{_abbr(name, 22)} · {made}/{len(shots)} en tiros de campo",
                             [img], half, accent=col))
    S.append(_cols(panels))
    S.append(Spacer(1, 4 * mm))

    rows = []
    for z in postgame.ZONES:
        x, y = zh[z], za[z]
        rows.append([
            postgame.ZONE_LABEL[z],
            _p(f"{x['made']}/{x['att']}", 7.8, TEXT, align=TA_RIGHT),
            _p(f"{x['pps']}", 7.8, HOME if x["pps"] >= y["pps"] else TEXT,
               bold=x["pps"] >= y["pps"], align=TA_RIGHT),
            _p(f"{x['share']}%", 7.4, DIM, align=TA_RIGHT),
            _p(f"{y['made']}/{y['att']}", 7.8, TEXT, align=TA_RIGHT),
            _p(f"{y['pps']}", 7.8, AWAY if y["pps"] > x["pps"] else TEXT,
               bold=y["pps"] > x["pps"], align=TA_RIGHT),
            _p(f"{y['share']}%", 7.4, DIM, align=TA_RIGHT),
        ])
    w = CONTENT_W
    S.append(_table(["Zona", f"{_abbr(hn, 12)} TC", "Pts/tiro", "Vol.",
                     f"{_abbr(an, 12)} TC", "Pts/tiro", "Vol."], rows,
                    [w * 0.22, w * 0.13, w * 0.11, w * 0.1, w * 0.13, w * 0.11, w * 0.1],
                    aligns=[None, "R", "R", "R", "R", "R", "R"], bold_first=True))
    S.append(Spacer(1, 4 * mm))

    hrows = []
    for side, name, col in (("home", hn, HOME), ("away", an, AWAY)):
        for hf in sh["halves"][side]:
            hrows.append([_p(f"{_abbr(name, 14)} · {hf['half']}", 7.4, col),
                          hf["tc"], hf["t3"], hf["tl"],
                          _p(str(hf["pts"]), 8, TEXT, bold=True, align=TA_RIGHT)])
    left = [_table(["Equipo", "TC", "Triples", "TL", "Puntos"], hrows,
                   [half * 0.38, half * 0.15, half * 0.17, half * 0.14, half * 0.16],
                   aligns=[None, "R", "R", "R", "R"])]

    def read(side, name):
        z = {x["zone"]: x for x in sh["zones"][side]}
        rim, c3, f3 = z["restringida"], z["triple_esquina"], z["triple_frontal"]
        return (f"<b>{_abbr(name, 24)}</b>: {rim['made']}/{rim['att']} en zona restringida "
                f"({rim['share']}% de sus tiros), {f3['made']}/{f3['att']} en triples "
                f"frontales y {c3['made']}/{c3['att']} desde la esquina.")

    right = [_p(read("home", hn), 8.2, TEXT, leading=11.4), Spacer(1, 2.4 * mm),
             _p(read("away", an), 8.2, TEXT, leading=11.4)]
    S.append(_cols([_titled("Por mitades", left, half),
                    _panel("Lectura", right, half, accent=AWAY)]))


# ---------------------------------------------------------------- 07 impacto
def _impact_page(S, rep, sec):
    im, mt = rep["impact"], rep["match"]
    hn, an = mt["home"]["name"], mt["away"]["name"]
    tops = im["top"]
    best = max(tops["home"] + tops["away"], key=lambda t: t["gmsc"], default=None)
    sec("Impacto, banquillo y faltas",
        f"{best['short']} fue el mejor del partido ({best['gmsc']} Game Score)"
        if best else "Impacto individual",
        "Ranking por Game Score (Hollinger, versión de un partido).")

    half = (CONTENT_W - 4 * mm) / 2
    panels = []
    for side, name, col in (("home", hn, HOME), ("away", an, AWAY)):
        rows = [[_p(t["short"], 8.2, TEXT, bold=True), t["min"],
                 _p(str(t["gmsc"]), 8.4, col, bold=True, align=TA_RIGHT),
                 str(t["val"]), str(t["pts"]),
                 _p(_signed(t["plus_minus"]), 7.8, _col(t["plus_minus"]), bold=True,
                    align=TA_RIGHT)] for t in tops[side]]
        panels.append(_panel(f"Top 3 · {_abbr(name, 22)}", [
            _table(["Jugador", "Min", "GmSc", "Val", "Pts", "+/-"], rows,
                   [half * 0.25, half * 0.15, half * 0.16, half * 0.11, half * 0.11,
                    half * 0.13],
                   aligns=[None, "R", "R", "R", "R", "R"], accent=col)], half, accent=col))
    S.append(_cols(panels))
    S.append(Spacer(1, 5 * mm))

    if not rep.get("starters"):
        S.append(_note("Titulares frente a suplentes no disponible: hace falta el "
                       "play-by-play del partido, porque el acta de la FEB no publica "
                       "quién salió de inicio.", accent=DIM))
        return

    rows = []
    for side, name, col in (("home", hn, HOME), ("away", an, AWAY)):
        for u in im["units"][side]:
            rows.append([_p(f"{_abbr(name, 15)} · {u['group']}", 7.6, col),
                         str(u["min"]), _p(str(u["pts"]), 8, TEXT, bold=True,
                                           align=TA_RIGHT),
                         f"{u['share']}%", str(u["pts40"]), f"{u['ts']}%", str(u["tov"])])
    w = CONTENT_W
    S.append(_titled("Titulares frente a suplentes", [
        _table(["Grupo", "Min", "Pts", "% del equipo", "Pts/40", "TS%", "Pérd."], rows,
               [w * 0.3, w * 0.1, w * 0.1, w * 0.16, w * 0.12, w * 0.12, w * 0.1],
               aligns=[None, "R", "R", "R", "R", "R", "R"]),
        Spacer(1, 1.6 * mm),
        _p("Titularidad tomada del play-by-play (los cinco que saltan en el 10:00 del "
           "Q1): el acta de la FEB no publica ese campo.", 6.6, DIM)], CONTENT_W))
    S.append(Spacer(1, 5 * mm))

    if im.get("fouls"):
        rows = []
        for side, name, col in (("home", hn, HOME), ("away", an, AWAY)):
            f = im["fouls"][side]
            early = " · ".join(f"{e['short']} ({e['at']})" for e in f["early_two"]) or "—"
            rows.append([_p(_abbr(name, 16), 7.6, col, bold=True),
                         " · ".join(str(x) for x in f["by_quarter"]),
                         _p(str(f["total"]), 8, TEXT, bold=True, align=TA_RIGHT),
                         f["opp_bonus_at"] or "—",
                         f"{f['opp_ft_made']}/{f['opp_ft_attempts']}",
                         _p(early, 7, DIM)])
        S.append(_titled("Faltas y bonus", [
            _table(["Equipo", "Por cuarto", "Total", "Rival en bonus", "TL del rival",
                    "2 faltas en 1ª mitad"], rows,
                   [w * 0.15, w * 0.15, w * 0.08, w * 0.15, w * 0.12, w * 0.35],
                   size=7.2)], CONTENT_W))


# ---------------------------------------------------------------- 08/09 boxscore
def _box_page(S, rep, sec, side):
    mt = rep["match"]
    name = mt[side]["name"]
    col = HOME if side == "home" else AWAY
    tot = rep["box"]["totals"][side]
    sec("Jugadores", f"Box score · {name}",
        f"{tot['pts']} puntos · {tot['tc']} en tiros de campo · {tot['t3']} en triples · "
        f"{tot['tl']} en libres")

    rows = []
    for b in rep["box"][side]:
        label = f"<font color='{_hex(DIM)}' size=6.6>#{b['dorsal'] or '—'}</font> {b['name']}"
        if b["starter"]:
            label += f"  <font color='{_hex(col)}' size=6><b>TIT</b></font>"
        pts = _p(str(b["pts"]), 8.4, col if b["pts"] >= 10 else TEXT,
                 bold=b["pts"] >= 10, align=TA_RIGHT)
        rows.append([_p(label, 7.5, TEXT), b["min"], pts, b["tc"], b["t3"], b["tl"],
                     str(b["oreb"]), str(b["dreb"]), str(b["ast"]), str(b["tov"]),
                     str(b["stl"]), str(b["pf"]), str(b["val"]),
                     _p(_signed(b["plus_minus"]), 7.5, _col(b["plus_minus"]), bold=True,
                        align=TA_RIGHT)])
    rows.append([_p("<b>TOTALES</b>", 7.6, TEXT), "",
                 _p(f"<b>{tot['pts']}</b>", 8.4, col, bold=True, align=TA_RIGHT),
                 tot["tc"], tot["t3"], tot["tl"], str(tot["oreb"]), str(tot["dreb"]),
                 str(tot["ast"]), str(tot["tov"]), str(tot["stl"]), str(tot["pf"]), "", ""])
    w = CONTENT_W
    widths = [w * 0.235, w * 0.06, w * 0.05, w * 0.07, w * 0.065, w * 0.065, w * 0.045,
              w * 0.045, w * 0.045, w * 0.045, w * 0.05, w * 0.045, w * 0.05, w * 0.07]
    t = _table(["Jugador", "Min", "Pts", "TC", "T3", "TL", "RO", "RD", "AS", "Pér",
                "Rob", "FC", "Val", "+/-"], rows, widths,
               aligns=[None] + ["R"] * 13, size=7.4, accent=col)
    t.setStyle(TableStyle([("LINEABOVE", (0, len(rows)), (-1, len(rows)), 1.0, col),
                           ("BACKGROUND", (0, len(rows)), (-1, len(rows)), GHOST)]))
    S.append(t)
    S.append(Spacer(1, 5 * mm))

    box = rep["box"][side]
    third = (CONTENT_W - 8 * mm) / 3
    scorers = sorted(box, key=lambda b: -b["pts"])[:4]
    b1 = [_p(" · ".join(f"<b>{b['short']}</b> {b['pts']}" for b in scorers if b["pts"])
             or "—", 8.2, TEXT, leading=11)]
    reb = sorted(box, key=lambda b: -b["treb"])[:3]
    b2 = [_p(" · ".join(f"<b>{b['short']}</b> {b['treb']} ({b['oreb']} of.)"
                        for b in reb if b["treb"]) or "—", 8.2, TEXT, leading=11)]
    alerts = []
    for b in box:
        if b["tov"] >= 4:
            alerts.append(f"<b>{b['short']}</b>: {b['tov']} pérdidas")
        if b["plus_minus"] <= -10:
            alerts.append(f"<b>{b['short']}</b>: {_signed(b['plus_minus'])}")
        if b["pf"] >= 4:
            alerts.append(f"<b>{b['short']}</b>: {b['pf']} faltas")
    b3 = [_p(" · ".join(alerts[:4]) or "Sin alertas destacadas.", 8.2, TEXT, leading=11)]
    S.append(_cols([_panel("Anotación", b1, third, accent=col),
                    _panel("Rebote", b2, third, accent=GOLD),
                    _panel("Alertas", b3, third, accent=BAD)]))
    S.append(Spacer(1, 4 * mm))
    S.append(_note("+/- oficial, validado contra el play-by-play. En un partido depende de "
                   "compañeros, rivales y momento: sirve para elegir vídeo, no para fijar "
                   "jerarquías.", accent=DIM))


# ---------------------------------------------------------------- 10 producción
def _production_page(S, rep, sec):
    mt = rep["match"]
    sec("Producción individual", "Uso, eficiencia y producción ofensiva",
        "%Uso del boxscore estándar; el resto, estimaciones de Dean Oliver.")
    w = CONTENT_W
    for side, name, col in (("home", mt["home"]["name"], HOME),
                            ("away", mt["away"]["name"], AWAY)):
        rows = []
        for p in rep["production"][side]:
            rows.append([_p(f"<font color='{_hex(DIM)}' size=6.4>#{p['dorsal'] or '—'}"
                            f"</font> {p['short']}", 7.4, TEXT),
                         str(p["min"]), f"{p['usg']}%", _na(p["ts"], "%"),
                         _p(str(p["gmsc"]), 7.6, col if p["gmsc"] >= 10 else TEXT,
                            bold=p["gmsc"] >= 10, align=TA_RIGHT),
                         str(p["pprod"]), _na(p["ortg"]), _na(p["floor"], "%"),
                         str(p["stops"]),
                         _p(_signed(p["plus_minus"]), 7.4, _col(p["plus_minus"]),
                            bold=True, align=TA_RIGHT)])
        S.append(_titled(name, [
            _table(["Jugador", "Min", "%Uso", "TS%", "GmSc", "Pts prod.",
                    "Ef. of.", "Floor%", "Stops", "+/-"], rows,
                   [w * 0.23, w * 0.07, w * 0.08, w * 0.08, w * 0.08, w * 0.11,
                    w * 0.09, w * 0.09, w * 0.08, w * 0.08],
                   aligns=[None] + ["R"] * 9, size=7.3, accent=col)], CONTENT_W,
            accent=col))
        S.append(Spacer(1, 4 * mm))
    S.append(_note(
        "<b>Pts producidos</b>, <b>eficiencia ofensiva individual</b>, <b>Floor%</b> y "
        "<b>Stops</b>: Dean Oliver (<i>Basketball on Paper</i>), implementación "
        "oliver_bref_v1. Son ESTIMACIONES y en un solo partido tienen muchísima varianza; "
        "eficiencia y Floor% solo se muestran con 10+ minutos.", accent=DIM))


# ---------------------------------------------------------------- 11/12 rotaciones
def _lineups_page(S, rep, sec, side):
    li = rep["lineups"][side]
    mt = rep["match"]
    name = mt[side]["name"]
    col = HOME if side == "home" else AWAY
    best_pair = max(li["pairs"], key=lambda p: p["plus_minus"], default=None)
    title = f"Rotaciones · {name}"
    if best_pair:
        title = (f"{_abbr(name, 20)}: {' – '.join(best_pair['players'])} "
                 f"({_signed(best_pair['plus_minus'])})")
    sec("Rotaciones", title,
        f"{li['distinct']} quintetos distintos" +
        (f" · quinteto inicial {li['starting']['min']} min "
         f"({_signed(li['starting']['plus_minus'])})" if li["starting"] else ""))

    half = (CONTENT_W - 4 * mm) / 2
    rows = [[_p(" · ".join(u["players"]), 7, TEXT), u["min"],
             _p(_signed(u["plus_minus"]), 7.6, _col(u["plus_minus"]), bold=True,
                align=TA_RIGHT), u["partial"]] for u in li["units"]]
    left = [_table(["Quinteto", "Min", "+/-", "Parcial"], rows or [["—"] * 4],
                   [half * 0.52, half * 0.15, half * 0.14, half * 0.17],
                   aligns=[None, "R", "R", "R"], size=7, accent=col)]

    prows = [[_p(" + ".join(p["players"]), 7.2, TEXT), str(p["min"]),
              _p(_signed(p["plus_minus"]), 7.6, _col(p["plus_minus"]), bold=True,
                 align=TA_RIGHT)] for p in li["pairs"]]
    trows = [[_p(" + ".join(p["players"]), 7.2, TEXT), str(p["min"]),
              _p(_signed(p["plus_minus"]), 7.6, _col(p["plus_minus"]), bold=True,
                 align=TA_RIGHT)] for p in li["trios"]]
    right = [_table(["Pareja · 8+ min", "Min", "+/-"], prows or [["—"] * 3],
                    [half * 0.58, half * 0.2, half * 0.2], aligns=[None, "R", "R"],
                    size=7, accent=col),
             Spacer(1, 3 * mm),
             _table(["Trío · 6+ min", "Min", "+/-"], trows or [["—"] * 3],
                    [half * 0.58, half * 0.2, half * 0.2], aligns=[None, "R", "R"],
                    size=7, accent=col)]

    S.append(_cols([_titled("Quintetos con 1:48 o más", left, half, accent=col),
                    _titled("Parejas y tríos", right, half, accent=col)]))
    S.append(Spacer(1, 4 * mm))
    top_min = li["units"][0]["min"] if li["units"] else "—"
    S.append(_note(
        f"<b>Qué NO concluir:</b> los quintetos están validados contra los minutos y el "
        f"+/- oficiales, pero ninguno pasa de {top_min} minutos. Con esas muestras son "
        f"índices para elegir vídeo, no veredictos. Las parejas y los tríos acumulan más "
        f"minutos, así que dan algo más de señal.", accent=BAD))


# ---------------------------------------------------------------- 13 claves
def _keys_page(S, rep, sec):
    sec("Claves de scouting", "Claves para preparar a cada equipo",
        "Salen de los números de ESTE partido: conviene contrastarlas con el informe "
        "de temporada antes de llevarlas a la pizarra.")
    half = (CONTENT_W - 4 * mm) / 2
    panels = []
    for side, col in (("home", HOME), ("away", AWAY)):
        k = rep["keys"][side]
        body = []
        for label, items in (("Qué quitarle", k["take_away"]),
                             ("Dónde atacarle", k["attack"]),
                             ("A vigilar", k["watch"])):
            body.append(_lbl(label, 6.6, col))
            body.append(Spacer(1, 1.2 * mm))
            for it in items:
                body.append(_p(f"— {it}", 8.2, TEXT, leading=11.4))
            body.append(Spacer(1, 3.5 * mm))
        panels.append(_panel(k["team"], body, half, accent=col))
    S.append(_cols(panels))


# ---------------------------------------------------------------- 14 calidad
def _quality_page(S, rep, sec):
    q = rep["quality"]
    sec("Calidad del dato", "Qué podemos afirmar y qué sería falsamente preciso",
        f"Nivel de dato de este informe: {q['level']}.")
    half = (CONTENT_W - 4 * mm) / 2
    ver, est = [], []
    for v in q["verified"]:
        ver.append(_p(f"— {v}", 8.2, TEXT, leading=11.2))
        ver.append(Spacer(1, 1.6 * mm))
    for v in q["estimated"]:
        est.append(_p(f"— {v}", 8.2, TEXT, leading=11.2))
        est.append(Spacer(1, 1.6 * mm))
    S.append(_cols([_panel("Verificado / reconciliado", ver or [_p("—", 8, DIM)], half,
                           accent=GOOD),
                    _panel("Estimado o limitado", est or [_p("—", 8, DIM)], half,
                           accent=BAD)]))
    S.append(Spacer(1, 5 * mm))

    defs = [
        ("Posesión real", "Serie de acciones ofensivas de un equipo (tiro, tiro libre, "
                          "pérdida, rebote ofensivo) que termina cuando el balón cambia "
                          "de manos."),
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
    def defs_col(items, width):
        body = []
        for label, text in items:
            body.append(_p(f"<b>{label}</b>", 7.4, TEXT))
            body.append(_p(text, 7, DIM, leading=9.2))
            body.append(Spacer(1, 1.5 * mm))
        return _box(body, width)

    mid = (len(defs) + 1) // 2
    S.append(_titled("Cómo se calcula cada cosa",
                     [_cols([defs_col(defs[:mid], half), defs_col(defs[mid:], half)])],
                     CONTENT_W))
    S.append(Spacer(1, 4 * mm))

    t = Table([[_p("CRITERIO PISCOUTING", 9, HOME, bold=True)],
               [_p("Dato oficial, cálculo derivado y reconstrucción van separados. "
                   "Lo validable se valida, lo estimado se etiqueta y lo que el feed no "
                   "permite calcular se omite en vez de rellenarse.", 8.6, TEXT,
                   leading=12)]],
              colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBEFORE", (0, 0), (0, -1), 3.4, HOME),
        ("BOX", (0, 0), (-1, -1), 0.6, HAIR),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 9), ("BOTTOMPADDING", (0, -1), (-1, -1), 11),
    ]))
    S.append(t)
