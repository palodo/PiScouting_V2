# Desplegar en una VM de Azure (crédito de estudiante)

Una VM Linux con Docker: backend siempre encendido + **SQLite local** (rápido y persistente)
+ Caddy (HTTPS automático) + actualización diaria por cron. La BBDD se siembra sola desde
`data/scouting.db.gz` la primera vez.

## 1. Crear la VM (portal de Azure)
En **portal.azure.com → Virtual machines → Create → Azure virtual machine**:
- **Image**: Ubuntu Server 22.04 LTS
- **Size**: `B1ms` (1 vCPU, 2 GB — de sobra y barata) o `B2s` (2 vCPU, 4 GB) si quieres holgura
- **Region**: West Europe (o Spain Central si te aparece)
- **Authentication**: SSH public key (te genera/descarga la clave)
- **Inbound ports**: marca **SSH (22)**, **HTTP (80)** y **HTTPS (443)**
- Crea y anota la **IP pública**.

## 2. Entrar por SSH
```powershell
ssh azureuser@LA_IP_PUBLICA
```

## 3. Instalar Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker   # aplica el grupo sin reloguear
```

## 4. Clonar el repo y configurar
```bash
git clone https://github.com/palodo/PiScouting_V2.git
cd PiScouting_V2
cp .env.example .env
nano .env    # rellena los valores (ver abajo) y guarda (Ctrl+O, Enter, Ctrl+X)
```
En `.env` define:
- `PISCOUTING_SECRET` y `PISCOUTING_ADMIN_TOKEN`: secretos aleatorios
  (genera con `openssl rand -base64 36`).
- `DOMAIN`: tu dominio del backend (p.ej. `api.tudominio.com`). Sin dominio aún, pon `DOMAIN=:80`.
- `FRONTEND_ORIGIN`: el dominio de tu web (p.ej. `https://palodo.github.io`).

## 5. (Si usas dominio) Apuntar el DNS
En tu proveedor de dominio, crea un registro **A**: `api.tudominio.com → LA_IP_PUBLICA`.
Caddy sacará el certificado HTTPS solo en el primer arranque.

## 6. Arrancar
```bash
docker compose up -d --build
```
La primera vez tarda un poco (construye la imagen y siembra la BBDD). Comprueba:
```bash
curl -s http://127.0.0.1:8080/api/health      # {"status":"ok", ...}
docker compose logs -f app                     # ver arranque/errores (Ctrl+C para salir)
```
Con dominio: abre `https://api.tudominio.com/api/health` en el navegador.

## 7. Actualización automática (cron de la VM)
Llama al endpoint del backend (así se limpia la caché del proceso vivo). Va **cada hora**,
no una vez al día: una pasada cuesta ~10 s y unas 5 peticiones a la FEB, y es lo que hace que
el **fantasy puntúe la jornada solo** en cuanto entra el último resultado (y que los
aplazamientos y cambios de horario se recojan el mismo día). Edita el cron:
```bash
crontab -e
```
y añade:
```
5 * * * * /home/azureuser/pi-refresh.sh >> /tmp/pi-refresh.log 2>&1
```
con `~/pi-refresh.sh` (`chmod +x`), que saca el token del `.env` y espera al resultado para
que quede en el log si algo falla:
```sh
#!/bin/sh
TOKEN=$(grep '^PISCOUTING_ADMIN_TOKEN=' /home/azureuser/PiScouting_V2/.env | cut -d= -f2)
date -Is
curl -fsS --max-time 900 -X POST "http://127.0.0.1:8080/api/admin/refresh?wait=true" \
  -H "X-Admin-Token: $TOKEN" | head -c 400
echo
```
Para comprobar que sigue vivo no hace falta entrar: `GET /api/health` trae `last_refresh`
con la fecha de la última pasada, si fue bien y cuántos partidos quedan por jugarse.

## 8. Conectar el frontend
Al construir la web, define `VITE_API_BASE = https://api.tudominio.com` (o `http://LA_IP` si sin
dominio) y asegúrate de que su dominio está en `FRONTEND_ORIGIN` (paso 4).

## Operar
- Actualizar el código: `git pull && docker compose up -d --build`. Las columnas nuevas del
  modelo se añaden solas al arrancar; la BBDD no hay que tocarla.
- Ver logs: `docker compose logs -f`.
- **Backup de la BBDD** (⚠️ un `cp` del fichero NO vale: SQLite va en WAL y los cambios
  recientes viven en `scouting.db-wal`, así que saldría una copia vieja y silenciosamente
  incompleta). Hay que pedirle a SQLite una copia consistente:
  ```bash
  docker compose exec -T app python -c "import sqlite3;s=sqlite3.connect('/data/scouting.db');d=sqlite3.connect('/data/backup.db');s.backup(d);d.close()"
  docker compose cp app:/data/backup.db ./backup_$(date +%F).db
  docker compose exec -T app rm /data/backup.db
  ```
- **No definas `DATABASE_URL`**: así usa el SQLite del volumen (local, rápido).

## Empezar una temporada nueva
El refresco se trae solo el calendario del curso siguiente en cuanto la FEB lo publica (lo
hace en verano, en cuanto la temporada en curso termina). Cuando quieras que la app pase a
la nueva, es una línea en el `.env` y reiniciar:
```
PISCOUTING_SEASON=2026
```
Las ligas fantasy ya creadas guardan su propia temporada, así que siguen donde estaban. Las
nuevas se crean contra la temporada real y, en cuanto se juegue la primera jornada, el
calendario de la FEB (día y hora de cada partido) manda sobre el mercado y el quinteto.

## Coste
Una `B1ms` encendida 24/7 ronda ~15 $/mes → con tu crédito de estudiante, gratis durante ~años.
