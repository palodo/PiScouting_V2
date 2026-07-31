"""Siembra la base de datos de producción a partir del dump del repo. Idempotente.

Pensado para ejecutarse en el build del despliegue (Render), de modo que no haya que
migrar nada a mano desde el portátil: el dump `data/scouting.db.gz` ya viaja en el repo.

- Sin DATABASE_URL (o con SQLite) no hace nada: en local se sigue usando data/scouting.db.
- Si Postgres ya tiene equipos, no hace nada. Reejecutarlo es seguro y NO borra las ligas.
- Con SEED_SKIP_SHOTS=1 se salta la tabla `shots` (~322k filas, el 84% del dump). El
  fantasy no la usa; el scouting sí, para los mapas de tiro.

    python seed_db.py
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401  (registra las tablas en SQLModel.metadata)
from app.config import DB_PATH
from migrate_to_postgres import TABLES, _normalize, copy_all

DUMP = Path(__file__).resolve().parent.parent / "data" / "scouting.db.gz"


def _already_seeded(url: str) -> bool:
    """True si Postgres ya tiene datos, para no duplicarlos en cada redeploy."""
    engine = create_engine(_normalize(url))
    with engine.connect() as conn:
        if not inspect(conn).has_table("teams"):
            return False
        return conn.execute(text("SELECT COUNT(*) FROM teams")).scalar_one() > 0


def main() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or url.startswith("sqlite"):
        print("seed: sin DATABASE_URL de Postgres, no hay nada que sembrar (local usa SQLite).")
        return

    if _already_seeded(url):
        print("seed: la base ya tiene datos, no se toca nada.")
        return

    if not DB_PATH.exists():
        if not DUMP.exists():
            sys.exit(f"seed: no encuentro ni {DB_PATH} ni el dump {DUMP}")
        print(f"seed: descomprimiendo {DUMP.name}…")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(DUMP, "rb") as fin, open(DB_PATH, "wb") as fout:
            shutil.copyfileobj(fin, fout)

    tables = TABLES
    if os.environ.get("SEED_SKIP_SHOTS", "").strip().lower() in ("1", "true", "yes"):
        tables = [t for t in TABLES if t != "shots"]
        print("seed: SEED_SKIP_SHOTS activo, se omiten los tiros (el fantasy no los usa).")

    print("seed: sembrando Postgres desde el dump del repo…")
    copy_all(DB_PATH, url, tables=tables)
    print("✅ seed: base lista.")


if __name__ == "__main__":
    main()
