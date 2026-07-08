"""CLI de ingesta de datos FEB.

Ejemplos:
  python ingest_cli.py --competition "1ª FEB" --limit 40      # prueba acotada
  python ingest_cli.py --all                                  # todo (largo)
  python ingest_cli.py --competition "3ª FEB" --group-codes 1 2 3 4 5 6
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlmodel import Session
from app.db import engine, init_db
from app.config import DEFAULT_SEASON, COMPETITIONS
from app.ingest.crawl import crawl_and_store


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingesta de datos FEB en la BBDD de PiScouting")
    ap.add_argument("--competition", help="1ª FEB | 2ª FEB | 3ª FEB")
    ap.add_argument("--all", action="store_true", help="Todas las categorías")
    ap.add_argument("--season", default=DEFAULT_SEASON)
    ap.add_argument("--limit", type=int, default=None, help="Máx. partidos con detalle")
    ap.add_argument("--no-details", action="store_true", help="Solo calendario/equipos")
    ap.add_argument("--group-codes", type=int, nargs="*", default=None)
    args = ap.parse_args()

    init_db()
    targets = list(COMPETITIONS.keys()) if args.all else [args.competition]
    if not targets or targets == [None]:
        ap.error("Indica --competition o --all")

    with Session(engine) as session:
        for comp in targets:
            summary = crawl_and_store(
                session, comp, args.season,
                group_codes=args.group_codes,
                ingest_details=not args.no_details,
                limit=args.limit,
                progress=lambda m: print(f"[{comp}] {m}", flush=True),
            )
            print(f"RESUMEN {comp}: {summary}", flush=True)


if __name__ == "__main__":
    main()
