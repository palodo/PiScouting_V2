# Desplegar PiScouting gratis (web)

Stack 100% gratuito y **sin tarjeta**:

| Pieza | Servicio | Gratis |
|---|---|---|
| Base de datos (Postgres) | **Neon** | 0.5 GB · persistente |
| Backend (FastAPI) | **Render** | web service free (se duerme tras 15 min) |
| Frontend (React) | **Cloudflare Pages** (o Vercel) | estático, siempre activo |

> La BBDD ocupa ~45 MB, así que cabe de sobra en el Postgres gratis de Neon.
> Único "pero": el backend gratis de Render **se duerme**; la primera visita tras un rato tarda ~30-60 s.

---

## 1. Base de datos → Neon

1. Crea cuenta en **https://neon.tech** (con GitHub/Google, sin tarjeta) y un proyecto.
2. Copia la **connection string** (algo como `postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require`).
3. Migra los datos locales a Neon (una sola vez):
   ```powershell
   cd backend
   # si no tienes la BBDD local, descomprímela:
   #   python -c "import gzip,shutil; shutil.copyfileobj(gzip.open('../data/scouting.db.gz','rb'), open('../data/scouting.db','wb'))"
   python -m pip install "psycopg[binary]" pandas
   python migrate_to_postgres.py "postgresql://...TU-URL-DE-NEON...?sslmode=require"
   ```
   Debe imprimir el nº de filas por tabla y `✅ Migración completada.`

## 2. Backend → Render

1. Asegúrate de que el repo está en GitHub (ya lo está: `github.com/palodo/PiScouting_V2`).
2. En **https://render.com** → **New → Blueprint** → conecta el repo (detecta `render.yaml`).
3. Define las variables de entorno del servicio `piscouting-api`:
   - `DATABASE_URL` = la connection string de Neon (paso 1).
   - `FRONTEND_ORIGIN` = *(la rellenas en el paso 3, con la URL de la web)*.
   - `PISCOUTING_SECRET` = déjala, se genera sola.
4. Deploy. Anota la URL del backend, p.ej. `https://piscouting-api.onrender.com`.
5. Comprueba: abre `https://piscouting-api.onrender.com/api/health` → debe devolver un JSON.

## 3. Frontend → Cloudflare Pages

1. En **https://pages.cloudflare.com** → **Create → Connect to Git** → elige el repo.
2. Configuración de build:
   - **Root directory:** `frontend`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Variable de entorno:** `VITE_API_BASE` = `https://piscouting-api.onrender.com` (la URL del paso 2)
3. Deploy. Anota la URL de la web, p.ej. `https://piscouting.pages.dev`.
4. Vuelve a **Render** → variable `FRONTEND_ORIGIN` = `https://piscouting.pages.dev` → guarda (redeploy).
   *(Esto habilita el CORS entre tu web y tu backend.)*

Listo: entra en tu URL de Cloudflare, crea una cuenta y a jugar. El `_redirects` ya está incluido
para que las rutas del fantasy (`/fantasy/:id`) funcionen al recargar.

---

## Notas y mantenimiento

- **Datos de prueba**: el usuario `pau@test.com` y todo el histórico quedan en Neon tras la migración.
- **Actualizar la web**: cada `git push` a `main` redepliega backend (Render) y frontend (Cloudflare) solos.
- **El backend se duerme** en el plan free: si quieres evitar el arranque en frío, un cron gratuito
  (p.ej. cron-job.org) que llame a `/api/health` cada 10 min lo mantiene despierto.
- **Alternativa a Cloudflare**: Vercel o Netlify sirven igual (mismo `VITE_API_BASE` y `_redirects`).
- **En local no cambia nada**: sin `DATABASE_URL` la app sigue usando SQLite como siempre.
