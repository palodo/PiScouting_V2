"""Actualización diaria de la BBDD desde la FEB (incremental e idempotente).

Cada día:
  1. Re-rastrea los calendarios de las categorías → actualiza fechas, jornadas, resultados
     y estado de los partidos (recoge aplazamientos y cambios de horario), y añade los nuevos.
  2. Ingiere el detalle (boxscore + tiros) SOLO de los partidos recién jugados (el pipeline
     salta los que ya tienen detalle).
  3. Vacía la caché para que los agregados se recalculen con lo nuevo.

Es seguro reejecutarla: idempotente. Un lock evita que se solapen dos ejecuciones.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from sqlmodel import Session

from .db import engine
from .config import DEFAULT_SEASON, COMPETITIONS
from .ingest.crawl import crawl_and_store
from .ingest.feb_client import FEBClient
from . import cache

log = logging.getLogger("piscouting.refresh")

_lock = threading.Lock()
_running = False
_last: dict = {}


def is_running() -> bool:
    return _running


def last_result() -> dict:
    return _last


def run_refresh(season: str | None = None, competitions: list[str] | None = None) -> dict:
    """Ejecuta la actualización. Devuelve un resumen. No lanza excepción hacia fuera."""
    global _running, _last
    if not _lock.acquire(blocking=False):
        return {"status": "already_running"}
    _running = True
    try:
        season = season or DEFAULT_SEASON
        comps = competitions or list(COMPETITIONS.keys())
        client = FEBClient()  # token global reutilizado entre categorías
        summary: dict = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "season": season, "competitions": {},
        }
        with Session(engine) as s:
            for comp in comps:
                try:
                    res = crawl_and_store(
                        s, comp, season, ingest_details=True, client=client,
                        progress=lambda m, c=comp: log.info("[%s] %s", c, m),
                    )
                    summary["competitions"][comp] = res
                except Exception as e:  # una categoría no debe tumbar el resto
                    log.exception("refresh de %s falló", comp)
                    summary["competitions"][comp] = {"error": str(e)}
        cleared = cache.clear()
        summary["cache_cleared"] = cleared
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        _last = summary
        log.info("refresh terminado: %s", {c: v.get("ingested", v) for c, v in summary["competitions"].items()})
        return summary
    finally:
        _running = False
        _lock.release()
