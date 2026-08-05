"""Motor de base de datos y sesiones."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

from .config import DATABASE_URL, IS_SQLITE

# SQLite necesita check_same_thread=False; Postgres no acepta esos connect_args.
_connect_args = {"check_same_thread": False, "timeout": 30} if IS_SQLITE else {}
# En Postgres (Neon free) recicla conexiones y comprueba que siguen vivas (evita cierres).
_engine_kw = {} if IS_SQLITE else {"pool_pre_ping": True, "pool_recycle": 300}

engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args, **_engine_kw)


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        """WAL + busy_timeout para permitir lectura (API) e ingesta concurrentes."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def _seed_sqlite_if_missing() -> None:
    """En SQLite, si la BBDD no existe todavía (p.ej. primer arranque en el volumen de Fly),
    la siembra descomprimiendo el dump del repo. Idempotente: si ya hay BBDD, no la toca
    (preserva usuarios/ligas fantasy)."""
    if not IS_SQLITE:
        return
    import gzip
    import shutil
    from pathlib import Path

    from .config import DB_PATH, DB_SEED_GZ

    db = Path(DB_PATH)
    if db.exists() and db.stat().st_size > 0:
        return
    if not Path(DB_SEED_GZ).exists():
        return  # sin dump: se creará una BBDD vacía
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_suffix(".seed.tmp")
    with gzip.open(DB_SEED_GZ, "rb") as fi, open(tmp, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    tmp.replace(db)


def init_db() -> None:
    """Siembra (si hace falta) y crea las tablas que no existan."""
    _seed_sqlite_if_missing()
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
