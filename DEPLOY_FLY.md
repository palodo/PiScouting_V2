# Desplegar el backend en Fly.io (SQLite en volumen)

La BBDD vive **en la misma máquina** que la app (SQLite en un volumen) → consultas en
microsegundos, sin latencia de red. Máquina **siempre encendida** (sin cold start).
Se siembra sola desde `data/scouting.db.gz` la primera vez; en los siguientes deploys
**no la toca** (conserva usuarios y ligas fantasy).

Ficheros ya listos en el repo: `Dockerfile`, `.dockerignore`, `fly.toml`.

## Pasos (una sola vez)

### 1. Instalar flyctl y entrar
```powershell
# Windows PowerShell
iwr https://fly.io/install.ps1 -useb | iex
fly auth signup   # o: fly auth login
```

### 2. Crear la app (sin desplegar todavía)
Desde la raíz del repo (usa el `fly.toml` que ya está):
```powershell
fly launch --no-deploy --copy-config --name piscouting-api --region mad
```
- Si el nombre `piscouting-api` está cogido, elige otro (será tu URL `https://EL-NOMBRE.fly.dev`)
  y cámbialo también en `fly.toml` (`app = "..."`).
- Si pregunta por Postgres/Redis: **No**. Si detecta el volumen del `fly.toml`, di que sí.

### 3. Crear el volumen de la BBDD
```powershell
fly volumes create piscouting_data --region mad --size 1
```

### 4. Definir los secretos
```powershell
fly secrets set `
  PISCOUTING_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" `
  PISCOUTING_ADMIN_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')" `
  FRONTEND_ORIGIN="https://TU-FRONTEND"
```
- `FRONTEND_ORIGIN` = el dominio donde sirves la web (p.ej. `https://palodo.github.io`).
  Se pueden poner varios separados por coma.
- Apunta el `PISCOUTING_ADMIN_TOKEN`: es el mismo que va en el secreto de GitHub Actions
  para la actualización diaria.

### 5. Desplegar
```powershell
fly deploy
```
Comprueba que responde:
```powershell
fly open /api/health     # debe devolver {"status":"ok", ...}
```

## Conectar el frontend
La web tiene que apuntar a la nueva API. Al **construir el frontend**, define la variable:
```
VITE_API_BASE = https://piscouting-api.fly.dev
```
(en GitHub Pages/Actions o donde compiles el frontend). Y asegúrate de que ese dominio del
frontend está en `FRONTEND_ORIGIN` (paso 4) para el CORS.

## Actualización diaria
El cron de GitHub Actions (`.github/workflows/daily-refresh.yml`) ya funciona: en los
secretos del repo pon `PISCOUTING_API_URL = https://piscouting-api.fly.dev` y
`PISCOUTING_ADMIN_TOKEN` = el mismo del paso 4.

## Notas
- **Una sola máquina**: SQLite en volumen = no escales a varias instancias (el volumen solo
  lo monta una máquina). Con `min_machines_running = 1` estás bien.
- **Backups**: haz snapshots del volumen de vez en cuando → `fly volumes snapshots list` /
  Fly los hace automáticos a diario. También puedes descargar el `.db` con `fly ssh`.
- **Coste**: una `shared-cpu-1x` 24/7 con 1 GB son unos pocos €/mes. Para ahorrar, baja a
  `memory = "512mb"` en `fly.toml` (suficiente salvo PDFs muy pesados).
- **Dejar de usar Neon**: en Fly NO definas `DATABASE_URL`; así usa el SQLite del volumen.
  (Neon/Render se pueden apagar cuando el frontend ya apunte a Fly.)
