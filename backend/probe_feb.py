"""Sondea la web de la FEB y dice qué hay publicado de cada temporada. Solo lectura.

No toca la base de datos ni necesita credenciales: sirve para comprobar, antes de montar
nada, si una temporada nueva ya está publicada y si los códigos de competición de
config.py siguen siendo válidos (la FEB los ha cambiado alguna vez entre temporadas).

    python probe_feb.py 2026            # una temporada
    python probe_feb.py 2025 2026       # compara con una que sabemos buena
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import COMPETITIONS
from app.ingest.calendar import crawl_calendar


def probe(season: str) -> bool:
    print(f"\n{'=' * 62}\nTEMPORADA {season}/{int(season) + 1}\n{'=' * 62}")
    algo = False
    for comp, cfg in COMPETITIONS.items():
        try:
            rows = crawl_calendar(cfg["calendar_slug"], season, cfg["calendar_code"])
        except Exception as e:
            print(f"  {comp:8s} ERROR: {type(e).__name__}: {e}")
            continue

        if not rows:
            print(f"  {comp:8s} sin partidos publicados todavía")
            continue

        algo = True
        grupos = sorted({r.get("grupo") or "?" for r in rows})
        jornadas = [r["jornada_num"] for r in rows if r.get("jornada_num")]
        con_resultado = sum(1 for r in rows if r.get("resultado"))
        equipos = {r.get("local") for r in rows} | {r.get("visitante") for r in rows}
        # la fecha viene como dd/mm/aaaa: hay que parsearla para ordenar cronológicamente
        fechas = sorted(
            (datetime.strptime(r["fecha"], "%d/%m/%Y").date() for r in rows if r.get("fecha")))

        print(f"  {comp:8s} {len(rows):5d} partidos · {len(equipos - {None}):3d} equipos "
              f"· {len(grupos)} grupo(s) · jornadas {min(jornadas, default=0)}-{max(jornadas, default=0)}")
        print(f"           jugados (con resultado): {con_resultado}")
        if fechas:
            print(f"           calendario del {fechas[0]} al {fechas[-1]}")
        if len(grupos) <= 8:
            print(f"           grupos: {', '.join(grupos)}")
        # Un reparto raro de jornadas suele delatar que el código de competición cambió
        top = Counter(jornadas).most_common(1)
        if top:
            print(f"           partidos por jornada (moda): {top[0][1]}")
    return algo


def main() -> None:
    seasons = sys.argv[1:] or ["2026"]
    resultados = {s: probe(s) for s in seasons}
    print(f"\n{'=' * 62}\nRESUMEN")
    for s, ok in resultados.items():
        print(f"  {s}/{int(s) + 1}: {'HAY DATOS' if ok else 'NADA PUBLICADO'}")


if __name__ == "__main__":
    main()
