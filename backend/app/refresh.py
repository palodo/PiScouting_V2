"""Actualización de la BBDD desde la FEB (incremental e idempotente).

Cada pasada:
  1. Re-rastrea los calendarios → fecha y HORA de cada partido, jornadas, resultados y
     estado (así entran los aplazamientos y los cambios de horario), y añade los nuevos.
  2. Ingiere el detalle (boxscore + tiros) SOLO de los partidos recién jugados (el pipeline
     salta los que ya lo tienen).
  3. Fuera de temporada, se trae también el calendario del curso siguiente en cuanto la FEB
     lo publica (lo hace en verano), para no depender de nadie al empezar.
  4. Vacía la caché para que los agregados se recalculen con lo nuevo.

Sale barata: el calendario entero de las tres categorías son ~5 peticiones y unos 10
segundos, así que se puede ejecutar cada hora. Eso es lo que mantiene vivo el fantasy sin
que nadie mire: en cuanto entra el último resultado de una jornada, se puntúa sola y el
mercado vuelve a abrir.

El resultado se guarda en disco (`refresh_last.json`, junto a la BBDD) para que sobreviva a
los reinicios y se pueda ver en `/api/health` sin entrar por SSH.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from sqlmodel import Session, select

from .db import engine
from .config import DEFAULT_SEASON, COMPETITIONS, DB_PATH
from .models import Match
from .ingest.crawl import crawl_and_store
from .ingest.feb_client import FEBClient
from . import cache

log = logging.getLogger("piscouting.refresh")

_lock = threading.Lock()
_running = False
_last: dict = {}

STATE_FILE = DB_PATH.parent / "refresh_last.json"


def is_running() -> bool:
    return _running


def last_result() -> dict:
    """Último resultado, leyendo del disco si el proceso acaba de arrancar."""
    global _last
    if not _last and STATE_FILE.exists():
        try:
            _last = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _last


def _save(summary: dict) -> None:
    global _last
    _last = summary
    try:
        STATE_FILE.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    except Exception:
        log.warning("no se pudo guardar el estado del refresh en %s", STATE_FILE)


def _pending_matches(session: Session, season: str) -> int:
    """Partidos de la temporada que aún no se han jugado. A cero = temporada terminada."""
    return len(session.exec(select(Match.id).where(Match.season == season,
                                                   Match.home_score == None)).all())  # noqa: E711


def next_season(season: str) -> str:
    try:
        return str(int(season) + 1)
    except (TypeError, ValueError):
        return ""


def run_refresh(season: str | None = None, competitions: list[str] | None = None) -> dict:
    """Ejecuta la actualización. Devuelve un resumen. No lanza excepción hacia fuera."""
    global _running
    if not _lock.acquire(blocking=False):
        return {"status": "already_running"}
    _running = True
    try:
        season = season or DEFAULT_SEASON
        comps = competitions or list(COMPETITIONS.keys())
        client = FEBClient()  # token global reutilizado entre categorías
        summary: dict = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "season": season, "competitions": {}, "ok": True,
        }
        with Session(engine) as s:
            for comp in comps:
                try:
                    summary["competitions"][comp] = crawl_and_store(
                        s, comp, season, ingest_details=True, client=client,
                        progress=lambda m, c=comp: log.info("[%s] %s", c, m),
                    )
                except Exception as e:  # una categoría no debe tumbar el resto
                    log.exception("refresh de %s falló", comp)
                    summary["competitions"][comp] = {"error": str(e)}
                    summary["ok"] = False

            summary["pending_matches"] = _pending_matches(s, season)
            # Temporada terminada: mirar si ya está publicada la siguiente. Solo calendario
            # (todavía no hay partidos jugados que ingerir).
            if summary["pending_matches"] == 0:
                nxt, encontrados = next_season(season), 0
                for comp in comps:
                    try:
                        res = crawl_and_store(s, comp, nxt, ingest_details=False, client=client,
                                              progress=lambda m: None)
                        encontrados += res.get("matches", 0)
                    except Exception as e:
                        log.warning("calendario %s de %s: %s", nxt, comp, e)
                summary["next_season"] = {"season": nxt, "matches": encontrados}

        summary["cache_cleared"] = cache.clear()
        # partidos sueltos que la FEB no sirvió: no es para alarmarse (`ok` sigue en pie),
        # pero si crece hay algo roto en la ingesta de detalle
        summary["match_errors"] = sum(v.get("errors", 0)
                                      for v in summary["competitions"].values())
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        _save(summary)
        log.info("refresh terminado: %s",
                 {c: v.get("ingested", v) for c, v in summary["competitions"].items()})
        return summary
    finally:
        _running = False
        _lock.release()
