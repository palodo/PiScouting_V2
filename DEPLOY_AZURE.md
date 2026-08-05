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

## 7. Actualización diaria (cron de la VM)
Llama al endpoint del backend (así se limpia la caché del proceso vivo). Edita el cron:
```bash
crontab -e
```
y añade (pon tu token; corre a las 05:00 UTC ~ 06-07h Madrid):
```
0 5 * * * curl -fsS -X POST http://127.0.0.1:8080/api/admin/refresh -H "X-Admin-Token: TU_ADMIN_TOKEN" >> /tmp/piscouting-refresh.log 2>&1
```

## 8. Conectar el frontend
Al construir la web, define `VITE_API_BASE = https://api.tudominio.com` (o `http://LA_IP` si sin
dominio) y asegúrate de que su dominio está en `FRONTEND_ORIGIN` (paso 4).

## Operar
- Actualizar el código: `git pull && docker compose up -d --build`.
- Ver logs: `docker compose logs -f`.
- Backup de la BBDD: `docker compose cp app:/data/scouting.db ./backup_$(date +%F).db`.
- **No definas `DATABASE_URL`**: así usa el SQLite del volumen (local, rápido).

## Coste
Una `B1ms` encendida 24/7 ronda ~15 $/mes → con tu crédito de estudiante, gratis durante ~años.
