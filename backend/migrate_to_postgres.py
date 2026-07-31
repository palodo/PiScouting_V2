"""Copia toda la base de datos local (SQLite) a un Postgres (p.ej. Neon).

Se ejecuta UNA vez, en local, apuntando a la URL de tu Postgres:

    cd backend
    python migrate_to_postgres.py "postgresql://usuario:pass@host/db?sslmode=require"
    # o:  set TARGET_DATABASE_URL=...  y luego  python migrate_to_postgres.py

Crea las tablas en Postgres (si no existen), copia los datos y reajusta las secuencias de
los IDs para que los siguientes registros (usuarios, ligas...) no choquen.
Necesita el driver de Postgres: pip install "psycopg[binary]"
"""
from __future__ import annotations

import os
import sys

import pandas as pd
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

from app import models  # noqa: F401  (registra las tablas en SQLModel.metadata)
from app.config import DB_PATH

# Orden respetando las claves foráneas
TABLES = ["teams", "players", "matches", "player_match_stats", "shots",
          "users", "fantasy_leagues", "fantasy_members", "fantasy_picks",
          "fantasy_listings", "fantasy_bids", "fantasy_events"]


def _normalize(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _coerce(df: "pd.DataFrame", table: str) -> "pd.DataFrame":
    """Adapta los tipos de SQLite a los de Postgres, según la metadata de los modelos.

    SQLite no tiene ni booleanos ni fechas nativas: guarda 0/1 y texto ISO. Postgres sí,
    y rechaza el INSERT si le llega un varchar donde espera timestamp. Derivamos las
    columnas a convertir de SQLModel.metadata para no mantener listas a mano.
    """
    cols = SQLModel.metadata.tables[table].columns
    for col in cols:
        if col.name not in df.columns:
            continue
        kind = col.type.__class__.__name__
        if kind == "Boolean":
            df[col.name] = df[col.name].astype(bool)
        elif kind in ("DateTime", "Date"):
            # errors="coerce" deja NaT en las fechas ilegibles; Postgres las acepta como NULL
            df[col.name] = pd.to_datetime(df[col.name], errors="coerce").astype(object).where(
                lambda s: s.notna(), None)
    return df


def main() -> None:
    target = os.environ.get("TARGET_DATABASE_URL") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not target:
        sys.exit('Uso: python migrate_to_postgres.py "<URL_POSTGRES>"  (o define TARGET_DATABASE_URL)')
    if not DB_PATH.exists():
        sys.exit(f"No existe la BBDD local: {DB_PATH} (descomprime data/scouting.db.gz primero)")

    src = create_engine(f"sqlite:///{DB_PATH}")
    tgt = create_engine(_normalize(target))

    print("Creando tablas en Postgres…")
    SQLModel.metadata.create_all(tgt)

    with src.connect() as sc:
        for t in TABLES:
            try:
                df = pd.read_sql(f"SELECT * FROM {t}", sc)
            except Exception as e:
                print(f"  {t}: omitida ({e})")
                continue
            df = _coerce(df, t)
            # trocea para no superar el límite de parámetros de Postgres (~65535)
            ncols = max(1, len(df.columns))
            chunk = max(1, 50000 // ncols)
            # dtype explícito: si una columna viene entera pero vacía (p.ej. winner_member_id
            # sin subastas resueltas), pandas la infiere como texto y Postgres rechaza el INSERT.
            dtype = {c.name: c.type for c in SQLModel.metadata.tables[t].columns
                     if c.name in df.columns}
            df.to_sql(t, tgt, if_exists="append", index=False, chunksize=chunk,
                      method="multi", dtype=dtype)
            print(f"  {t}: {len(df)} filas")

    print("Reajustando secuencias de IDs…")
    with tgt.begin() as conn:
        for t in TABLES:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM {t}))"
            ))
    print("✅ Migración completada.")


if __name__ == "__main__":
    main()
