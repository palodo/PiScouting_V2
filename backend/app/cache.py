"""Caché en memoria para agregados estáticos de la FEB.

La temporada está finalizada: rankings, clasificaciones, stats de equipo/jugador y tiros
NO cambian, así que se calculan una vez y se sirven desde memoria. Esto evita el problema
de rendimiento en producción: muchas consultas pequeñas (patrón N+1) × la latencia de la
BBDD remota (Neon). Con la caché, cada agregado toca la BBDD una sola vez.

Uso: decorar funciones cuyo primer argumento sea la `Session` y que devuelvan estructuras
serializables (dicts/listas). El fantasy NO se cachea (tiene escrituras).

`clear()` se llama cuando se ingiere nuevo detalle (p.ej. «Preparar scouting»), porque eso
sí cambia los agregados del equipo afectado.
"""
from __future__ import annotations

import copy
import functools
import threading

_store: dict = {}
_lock = threading.Lock()


def cached(fn):
    """Cachea el resultado de `fn(session, *args, **kwargs)` por (args, kwargs).

    Devuelve siempre una copia profunda para que quien la use pueda mutarla sin
    corromper la caché (p.ej. el simulador de jornada modifica el calendario)."""
    @functools.wraps(fn)
    def wrap(session, *args, **kwargs):
        key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
        with _lock:
            if key in _store:
                return copy.deepcopy(_store[key])
        value = fn(session, *args, **kwargs)
        with _lock:
            _store[key] = value
        return copy.deepcopy(value)
    return wrap


def clear() -> int:
    """Vacía la caché (tras ingerir datos nuevos). Devuelve cuántas entradas había."""
    with _lock:
        n = len(_store)
        _store.clear()
    return n


def size() -> int:
    with _lock:
        return len(_store)
