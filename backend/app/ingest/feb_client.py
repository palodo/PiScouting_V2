"""Cliente HTTP para las fuentes de datos de la FEB.

Dos superficies:
  1. Web pública (baloncestoenvivo.feb.es): clasificación y calendario (ASP.NET WebForms).
  2. LiveStats API (intrafeb.feb.es): boxscore + shotchart por partido, protegido por
     un token Bearer que se extrae de la página del partido.

La llamada a un endpoint de LiveStats devuelve un "envelope" con muchas secciones
(HEADER, BOXSCORE, SHOTCHART, ...), pero cada endpoint solo rellena la suya. Por eso
pedimos ShotChart y Boxscore por separado y los combinamos.
"""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from ..config import FEB_BASE, LIVESTATS_API, USER_AGENT, REQUEST_PAUSE


def team_code_from_url(url: str) -> Optional[str]:
    """Extrae el código de equipo (parámetro i=) de una URL Equipo.aspx?i=NNNN."""
    if not url:
        return None
    m = re.search(r"[?&]i=(\d+)", url)
    return m.group(1) if m else None


def partido_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    for pat in (r"/partido/(\d+)", r"[?&]p=(\d+)"):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    try:
        q = parse_qs(urlparse(url).query)
        return (q.get("p") or [None])[0]
    except Exception:
        return None


class FEBClient:
    def __init__(self, pause: float = REQUEST_PAUSE):
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        })
        self._token: Optional[str] = None

    # -------- LiveStats API --------
    def _ensure_token(self, partido_id: str) -> str:
        """Obtiene (y cachea) el token Bearer. El token es GLOBAL: sirve para cualquier
        partido de cualquier categoría, así que solo descargamos la pesada página HTML
        del partido una vez por sesión (no una vez por partido)."""
        if self._token:
            return self._token
        url = f"{FEB_BASE}/partido/{partido_id}"
        r = self.session.get(url, headers={"Referer": url}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        tok = soup.find("input", {"name": "_ctl0:token"})
        if not tok or not tok.get("value"):
            raise RuntimeError(f"No se pudo obtener token para partido {partido_id}")
        self._token = tok["value"]
        return self._token

    def _livestats(self, endpoint: str, partido_id: str, _retry: bool = True) -> dict:
        token = self._ensure_token(partido_id)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Referer": f"{FEB_BASE}/partido/{partido_id}",
            "Origin": FEB_BASE,
        }
        r = self.session.get(
            f"{LIVESTATS_API}/{endpoint}/{partido_id}", headers=headers, timeout=30
        )
        if r.status_code == 401 and _retry:
            # Token expirado -> refrescar y reintentar una vez
            self._token = None
            return self._livestats(endpoint, partido_id, _retry=False)
        r.raise_for_status()
        return r.json()

    def get_match_data(self, partido_id: str) -> dict:
        """Devuelve HEADER, BOXSCORE y SHOTCHART combinados para un partido."""
        shot = self._livestats("ShotChart", partido_id)
        box = self._livestats("Boxscore", partido_id)
        if self.pause:
            time.sleep(self.pause)  # cortesía con el servidor FEB, una vez por partido
        return {
            "HEADER": box.get("HEADER") or shot.get("HEADER") or {},
            "BOXSCORE": box.get("BOXSCORE") or {},
            "SHOTCHART": shot.get("SHOTCHART") or {},
        }

    # -------- Web pública (GET simple) --------
    def get_soup(self, url: str) -> BeautifulSoup:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        if not r.encoding:
            r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "lxml")

    def get(self, url: str) -> requests.Response:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        if not r.encoding:
            r.encoding = r.apparent_encoding or "utf-8"
        return r
