# PiScouting v2

Aplicación web de **scouting de baloncesto FEB** (1ª, 2ª y 3ª FEB). Evoluciona el antiguo
bot de Telegram + PDF hacia una app interactiva con base de datos **partido a partido**:
rankings, +/- por jugador, mapas de tiro (animados), comparativas, y **scouting completo
del próximo rival** al estilo de los informes en PDF originales.

## Arquitectura

```
backend/    FastAPI + SQLModel (SQLite)  ->  API REST + ingesta de datos FEB
  app/
    models.py        Modelo de datos (users, teams, players, matches, stats, shots)
    main.py          Endpoints (auth, rankings, scouting, tiros, comparativa)
    auth.py          Registro/login (PBKDF2 + JWT)
    analytics.py     Agregados (récord, roster, líderes, TS%…)
    scouting.py      Informe del rival, calendario, próximo rival, simulador de jornada
    postgame.py      Informe post-partido: posesiones, quintetos, rachas, zonas de tiro
    postgame_pdf.py  El mismo informe en PDF (vertical, 15 páginas)
    shots.py         Normalización de tiros a media pista
    ingest/          Cliente FEB, scraper de calendario y pipeline de ingesta
  ingest_cli.py      CLI para poblar la base de datos
frontend/   React + Vite + TypeScript    ->  UI (login, mi equipo, scouting, rankings)
data/       scouting.db (generada) + assets (imagen de pista)
```

### De dónde salen los datos
Fuente: `baloncestoenvivo.feb.es` (calendario/clasificación) + la **LiveStats API**
(`intrafeb.feb.es`). Por cada partido se obtienen boxscore completo —incluido el **+/-**
(campo `pllss`)— y el shotchart con coordenadas + reloj + cuarto (base de los mapas animados).
Para los informes post-partido se baja además el **play-by-play** completo (~500 jugadas).

Tres claves descubiertas y aprovechadas:
- El **token** de la LiveStats API es **global**: sirve para cualquier partido de cualquier
  categoría, así que se descarga una sola vez (evita ~2400 descargas de HTML → ingesta ~4× más rápida).
- El `code` de la URL de calendario selecciona la categoría: **1 = 1ª FEB, 2 = 2ª FEB, 5 = 3ª FEB**.
- El **play-by-play** no lo sirve ningún endpoint `PlayByPlay` (404): va dentro de **`KeyFacts`**,
  con coordenadas y valor de cada tiro. Es lo que permite reconstruir el partido jugada a jugada.

## Puesta en marcha

### Arranque rápido (Windows)
Doble clic en **`start.bat`**: arranca backend + frontend y abre la app en el navegador.
La primera vez, instala dependencias antes (pasos 1 y 3). Manualmente:

### 1) Backend
```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```
API en http://127.0.0.1:8000 · docs en http://127.0.0.1:8000/docs

### 2) Ingesta de datos
```powershell
cd backend
python ingest_cli.py --all                       # todas las categorías (equipos + detalle)
python ingest_cli.py --competition "1ª FEB"       # una categoría completa
python ingest_cli.py --all --no-details           # solo equipos y calendarios (rápido)
```
Idempotente: reejecutarla actualiza en vez de duplicar. El calendario llena
clasificación/resultados al instante; el detalle (boxscore + tiros) también se puede
descargar **bajo demanda** por equipo desde el botón «Preparar scouting» de la app.

### 3) Frontend
```powershell
cd frontend
npm install
npm run dev
```
UI en http://127.0.0.1:5173 (proxy de `/api` al backend en el 8000).

## Funcionalidades
- **Cuenta y login**: registro con email + contraseña (PBKDF2 + JWT); eliges tu equipo.
- **Mi equipo**: balance, calendario, **próximo rival automático** y **simulador de jornada**
  (para revisar el análisis como si estuvieras a mitad de temporada).
- **Scouting del rival** (tipo los PDF originales): puesto en el grupo, métricas avanzadas
  (OffRtg, ritmo, eFG%, TS%, AST/TO, % de tiros de 3), clasificación, **jugadores clave** con
  foto y mapa de tiro, y plantilla con +/- y TS%. **Exportable a PDF** (informe descargable).
- **Informes post-partido**: de cada partido jugado, un informe completo al estilo de los
  informes profesionales, en la app y **en PDF de 15 páginas**. Lleva resumen ejecutivo,
  evolución del marcador con rachas y sequías, fases de cada cuarto y tiempos muertos, four
  factors, **economía de posesión** (de dónde sale cada punto: tras robo, tras rebote, segundas
  oportunidades, puntos rápidos), perfil de tiro por zonas, box score, producción individual
  (Oliver), **quintetos, parejas y tríos** con su +/-, claves de scouting y una última página de
  calidad del dato. Todo se reconstruye del play-by-play, y los minutos y el +/- se **validan
  contra el acta oficial**: si algo no cuadra, el informe lo dice.
- **Rankings**: clasificación por categoría/grupo y líderes por estadística.
- **Fichas** de equipo / jugador / partido con **mapas de tiro** (animados en jugador y partido).
- **Comparar**: enfrenta las medias de dos equipos.

## Pendiente / próximos pasos
- Llevar al mapa de tiro de temporada la geometría ya calibrada en el informe post-partido.
- Que el simulador de jornada acote también el scouting del rival a sus partidos hasta esa fecha.
- Refresco incremental por jornada (tarea programada) y narrativa de scouting con IA + export a PDF.
- Heatmap de tiro (el % por zona ya está en el informe post-partido) y comparación directa
  rival vs. tu equipo.
