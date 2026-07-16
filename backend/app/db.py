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


def init_db() -> None:
    """Crea las tablas si no existen. Importa models para registrarlos en metadata."""
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
