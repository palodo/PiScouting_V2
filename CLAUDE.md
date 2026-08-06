# Instrucciones para el agente (PiScouting v2)

App de scouting de baloncesto FEB: **backend FastAPI + SQLite** (`backend/`) y
**frontend React + Vite** (`frontend/`). Visión general y funcionalidades en [README.md](README.md).

> ⚠️ La base de datos `data/scouting.db` **no está en git** (es grande y regenerable).
> En un ordenador nuevo hay que montarla con uno de los dos métodos de abajo **antes** de
> arrancar el backend.

## 1. Montar la base de datos

### Opción A — usar el dump incluido (rápido, recomendado)
El repo trae `data/scouting.db.gz` (~18 MB) con TODOS los datos ya ingeridos
(184 equipos, 2.430 partidos, ~55k líneas de boxscore, ~322k tiros de 1ª/2ª/3ª FEB).
Descomprímelo a `data/scouting.db`:

```powershell
# Windows PowerShell (no requiere herramientas extra)
cd C:\ruta\a\PiScoutingv2
python -c "import gzip,shutil; shutil.copyfileobj(gzip.open('data/scouting.db.gz','rb'), open('data/scouting.db','wb'))"
```
```bash
# Git Bash / Linux / Mac (deja el .gz y crea data/scouting.db)
gzip -dk data/scouting.db.gz
```

### Opción B — regenerar desde cero (~20-25 min, descarga de la FEB)
Si el dump no está o quieres datos frescos:
```powershell
cd backend
python -m pip install -r requirements.txt
python ingest_cli.py --all              # calendario + detalle de las 3 categorías
```
Variantes: `--all --no-details` (solo equipos/calendarios, rápido) · `--competition "1ª FEB"`.
La ingesta es **idempotente** (reejecutar actualiza, no duplica).

## 2. Arrancar la app

```powershell
# Terminal 1 — backend (necesita data/scouting.db)
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```
Web en http://localhost:5173 · API en http://127.0.0.1:8000/docs.
En Windows también sirve el doble clic en `start.bat` (arranca ambos + navegador).

La cuenta de prueba (`pau@test.com`) solo existe si usaste el dump (Opción A). Con la Opción B,
crea una cuenta nueva en la app (registro con email+contraseña y elección de equipo).

**Config opcional**: copia `.env.example` a `.env` (raíz del repo) para fijar `PISCOUTING_SECRET`
(secreto de los JWT). El backend carga `.env` solo; en dev funciona sin él con un secreto por defecto.

## 3. Cosas que debes saber (no las vuelvas a descubrir)

- **Entorno**: Python 3.14 (`python`, no `python3`) y Node 24. En scripts de consola exporta
  `PYTHONUTF8=1` o verás mojibake al imprimir acentos (los datos en BBDD están bien en UTF-8).
- **Fuente de datos**: web `baloncestoenvivo.feb.es` + **LiveStats API** `intrafeb.feb.es`.
  Por cada partido: `Boxscore` (incluye **+/-** en el campo `pllss`) y `ShotChart` (tiros con
  coordenadas + reloj + cuarto). Cliente en `backend/app/ingest/feb_client.py`.
- **Token global**: el Bearer de la LiveStats API sirve para CUALQUIER partido y categoría; se
  descarga una vez por sesión (no por partido). No lo rompas: es lo que hace la ingesta ~4× más rápida.
- **Códigos de categoría** (URL de calendario): **1 = 1ª FEB, 2 = 2ª FEB, 5 = 3ª FEB**
  (el slug de la URL es cosmético). En `backend/app/config.py`.
- **Detalle bajo demanda**: `POST /api/scout/{team_id}/prepare` ingiere boxscore+tiros de un
  equipo al vuelo (`crawl.ingest_team`). Es lo que dispara el botón «Preparar scouting».
- **SQLite en WAL**: `db.py` activa WAL + busy_timeout para permitir leer (API) y escribir
  (ingesta) a la vez. No lo quites o habrá "database is locked".
- **Temporada 2025/26 finalizada**: todos los partidos están jugados, por eso el "próximo rival"
  usa el **simulador de jornada** de la página «Mi equipo».
- **Fantasy: la liga va por fases** (`fantasy.league_state`), y de ahí cuelga todo lo demás:
  `mercado` (tandas diarias, se ficha) → `alineacion` (mercado cerrado, solo quinteto) →
  `jornada` (todo bloqueado hasta que se juegue, aplazamientos incluidos; se puntúa sola).
  Cualquier acción que mueva dinero o el quinteto pasa por `_require(...)`.
- **Simulación vs temporada real**: `sim_mode` lo decide sola `create_league` mirando si
  quedan partidos por jugarse (`season_progress`). En simulación el reloj es el calendario
  propio de la liga (`play_weekday` + `play_hour`, semanal); en real manda `Match.start_at`,
  la fecha y **hora** de cada partido tal cual las publica la FEB. Ojo: la fecha del título
  de la jornada NO sirve (la jornada se reparte entre varios días), por eso el calendario se
  parsea partido a partido (`td.fecha`, "SÁBADO 26/09/2026 19:00"). La hora solo está
  mientras el partido no se ha jugado: una vez jugado la FEB la quita, así que nunca se pisa
  `start_at` con None.
- **Autonomía**: `refresh.run_refresh()` (endpoint `POST /api/admin/refresh`) cuesta ~10 s y
  5 peticiones, así que va en un **cron cada hora** en la VM. Es lo que puntúa la jornada
  sola y recoge aplazamientos. Deja el resultado en `data/refresh_last.json` y asomado en
  `/api/health` (`last_refresh`), que es como se ve desde fuera que sigue vivo. Fuera de
  temporada se trae solo el calendario del curso siguiente; para pasar la app a esa
  temporada, `PISCOUTING_SEASON=2026` en el `.env`.
- **Fantasy en simulación**: las estadísticas se recortan SIEMPRE a `current_jornada`
  (`all_priced`, `player_detail`); si no, la ficha destripa partidos que en la liga no se han
  jugado. Al tocar cualquier consulta nueva, mantener ese filtro.
- **Columnas nuevas**: `db.init_db()` llama a `_add_missing_columns()`, que hace `ALTER TABLE
  ADD COLUMN` de lo que falte (SQLite y Postgres). Añadir campos al modelo es seguro; renombrar
  o borrar no está soportado.
- **Informe PDF**: `backend/app/pdf_report.py` (ReportLab + Pillow, sin matplotlib), horizontal y
  visual. Endpoint `GET /api/scout/{id}/pdf`. Los mapas de tiro se pintan sobre la mitad derecha
  de `data/basket_court_edited.png`.
- **Ficheros gitignored** (se regeneran): `data/scouting.db`, `data/player_photos_cache/`,
  `data/team_logos_cache/`, `node_modules/`, `*.log`, `_original/` (proyecto viejo de referencia).

## 4. Pendiente / próximos pasos
- Calibrar con precisión las coordenadas del shotchart FEB contra la pista real
  (ahora los tiros se reparten algo anchos por la media pista).
- Que el simulador de jornada acote también el scouting del rival a sus partidos hasta esa fecha.
- Refresco incremental por jornada (tarea programada) y narrativa de scouting con IA.
