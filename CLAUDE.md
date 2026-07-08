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
