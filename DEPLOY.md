# Desplegar gratis (web)

> El proyecto tiene **dos webs independientes** que comparten backend:
> - `frontend/` → **PiScouting** (scouting, informes PDF, rankings). Puerto 5173 en local.
> - `fantasy-web/` → **PiFantasy** (la app de fantasy con mercado de subastas). Puerto 5174.
>
> Puedes desplegar solo una o las dos: son dos proyectos separados en Cloudflare/Vercel,
> cada uno con su `VITE_API_BASE` apuntando al mismo backend. Añade **ambos** dominios a
> `FRONTEND_ORIGIN` (separados por coma) en Render.



Stack 100% gratuito y **sin tarjeta**:

| Pieza | Servicio | Gratis |
|---|---|---|
| Base de datos (Postgres) | **Neon** | 0.5 GB · persistente |
| Backend (FastAPI) | **Render** | web service free (se duerme tras 15 min) |
| Frontend (React) | **Cloudflare Pages** (o Vercel) | estático, siempre activo |

> La BBDD ocupa ~45 MB, así que cabe de sobra en el Postgres gratis de Neon.
> Único "pero": el backend gratis de Render **se duerme**; la primera visita tras un rato tarda ~30-60 s.

---

## Atajo: publicar solo PiFantasy (unos 15 min, todo desde el navegador)

Si solo quieres que unos amigos prueben el fantasy, **no hace falta migrar nada a mano**:
el backend siembra la base él solo en el primer deploy, a partir del dump del repo.

1. **Neon** → entra en https://neon.tech con GitHub, crea un proyecto y copia la
   *connection string* (`postgresql://…?sslmode=require`).
2. **Render** → https://render.com con GitHub → **New → Blueprint** → elige este repo
   (detecta `render.yaml`) → pega la cadena de Neon en `DATABASE_URL` → **Deploy**.
   El build siembra la base y arranca la API; el primer deploy tarda unos minutos (sube
   ~61k filas a Neon). Copia la URL, p.ej. `https://piscouting-api.onrender.com`.
3. **Cloudflare Pages** → https://pages.cloudflare.com con GitHub → **Create → Connect to Git**
   → este repo → **Root directory:** `fantasy-web` · **Build command:** `npm run build`
   · **Output:** `dist` · variable `VITE_API_BASE` = la URL de Render → **Deploy**.
4. Vuelve a Render → `FRONTEND_ORIGIN` = la URL de Cloudflare → guarda.

Ya está: pasa la URL de Cloudflare a tus amigos, que se creen cuenta, y el que cree la liga
comparte el **código de invitación** que sale arriba para que los demás entren con «Unirme».

> El paso 3 es el único que se puede saltar si prefieres probarlo tú solo en local
> (`cd fantasy-web && npm run dev` apuntando al backend de Render con `VITE_API_BASE`).

---

## 1. Base de datos → Neon

Con el atajo de arriba **este paso ya está hecho** (lo hace `seed_db.py` en el build).
Migra a mano solo si quieres subir tus datos locales — ligas y usuarios incluidos —
en vez del dump del repo:

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
   - `SEED_SKIP_SHOTS` = viene a `1` (siembra sin los ~322k tiros, que el fantasy no usa).
     Ponlo a `0` **antes del primer deploy** si quieres los mapas de tiro del scouting:
     el sembrado solo ocurre una vez, después ya no vuelve a tocar la base.
   - `FRONTEND_ORIGIN` = *(la rellenas en el paso 3, con la URL de la web)*.
   - `PISCOUTING_SECRET` = déjala, se genera sola.
4. Deploy. Anota la URL del backend, p.ej. `https://piscouting-api.onrender.com`.
5. Comprueba: abre `https://piscouting-api.onrender.com/api/health` → debe devolver un JSON.

## 3. Webs → Cloudflare Pages

Son **dos proyectos separados** en Cloudflare, uno por cada web. Repite estos pasos para cada
uno cambiando solo el *root directory*:

| Web | Root directory | URL de ejemplo |
|---|---|---|
| PiScouting | `frontend` | `https://piscouting.pages.dev` |
| PiFantasy | `fantasy-web` | `https://pifantasy.pages.dev` |

1. En **https://pages.cloudflare.com** → **Create → Connect to Git** → elige el repo.
2. Configuración de build:
   - **Root directory:** `frontend` (o `fantasy-web`)
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Variable de entorno:** `VITE_API_BASE` = `https://piscouting-api.onrender.com` (la URL del paso 2)
3. Deploy y anota la URL.
4. Cuando tengas las dos, vuelve a **Render** → `FRONTEND_ORIGIN` =
   `https://piscouting.pages.dev,https://pifantasy.pages.dev` (**separadas por coma, sin espacios**)
   → guarda (redeploy). *(Esto habilita el CORS entre tus webs y el backend.)*

Listo: entra en cualquiera de las dos URLs, crea una cuenta y a jugar. El `_redirects` de cada web
ya está incluido para que las rutas internas funcionen al recargar.

> Las dos webs comparten backend y base de datos, pero **no la sesión**: cada una guarda su propio
> token (`pi_token` y `pf_token`), así que tendrás que entrar en cada una por separado aunque la
> cuenta sea la misma.

---

## Notas y mantenimiento

- **Datos de prueba**: el usuario `pau@test.com` y todo el histórico quedan en Neon tras la migración.
- **Actualizar la web**: cada `git push` a `main` redepliega backend (Render) y frontend (Cloudflare) solos.
- **El backend se duerme** en el plan free: si quieres evitar el arranque en frío, un cron gratuito
  (p.ej. cron-job.org) que llame a `/api/health` cada 10 min lo mantiene despierto.
- **El mercado del fantasy no necesita cron**: `sync_market` abre y cierra las tandas de forma
  perezosa, al primer acceso a la liga. Aunque Render duerma el backend justo a la hora de cierre,
  las pujas se resuelven en cuanto alguien entra; solo se retrasa el aviso, no el resultado.
- **Alternativa a Cloudflare**: Vercel o Netlify sirven igual (mismo `VITE_API_BASE` y `_redirects`).
- **En local no cambia nada**: sin `DATABASE_URL` la app sigue usando SQLite como siempre.
