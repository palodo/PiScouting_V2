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


def _add_missing_columns() -> None:
    """Añade las columnas nuevas del modelo que falten en la BBDD.

    `create_all` crea tablas, pero NO altera las que ya existen: sin esto, una BBDD viva
    (la del volumen de la VM, con sus ligas y usuarios) se queda con el esquema antiguo y
    el backend revienta al leer un campo nuevo. Solo se añaden columnas (con su valor por
    defecto); nunca se borra ni se cambia nada, así que es seguro ejecutarlo en cada arranque.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateColumn

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = CreateColumn(col).compile(engine).string
                # Una columna añadida a una tabla con filas no puede ser NOT NULL sin default.
                ddl = ddl.replace(" NOT NULL", "")
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
                default = getattr(col.default, "arg", None)
                if default is not None and not callable(default):
                    conn.execute(text(f'UPDATE "{table.name}" SET "{col.name}" = :v'
                                      f' WHERE "{col.name}" IS NULL'), {"v": default})


def init_db() -> None:
    """Siembra (si hace falta), crea las tablas que no existan y migra las columnas nuevas."""
    _seed_sqlite_if_missing()
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
