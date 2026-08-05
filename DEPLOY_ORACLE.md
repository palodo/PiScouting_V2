# Desplegar en Oracle Cloud — Always Free (gratis para siempre)

Una VM ARM "Always Free" (siempre encendida, gratis de verdad) con Docker: backend +
SQLite local (rápido y persistente) + Caddy (HTTPS) + actualización diaria por cron.
El Docker es multi-arquitectura, así que corre en ARM sin cambios.

## 1. Crear la cuenta
En **cloud.oracle.com → "Start for free"**. Necesitas email, teléfono y una **tarjeta solo
para verificar** (NO cobran por los recursos Always Free).
- **Home Region**: elige una cerca de España y **no se puede cambiar luego** → *Spain Central
  (Madrid)*, *Germany Central (Frankfurt)* o *France South (Marseille)*.

## 2. Crear la VM (Always Free, ARM)
**Compute → Instances → Create instance**:
- **Image**: Canonical Ubuntu 22.04.
- **Shape**: *Change shape* → **Ampere (ARM)** → `VM.Standard.A1.Flex` →
  **2 OCPU / 12 GB RAM** (dentro del Always Free de 4 OCPU / 24 GB). Debe decir *Always Free-eligible*.
- **SSH keys**: sube tu clave pública (o genera una y descárgala).
- **Networking**: deja que cree una VCN nueva con subred pública e IP pública. Anota la **IP pública**.

> ⚠️ Si sale **"Out of host capacity"** (pasa con ARM en regiones llenas): reintenta más tarde,
> prueba otro *Availability Domain*, o como plan B usa `VM.Standard.E2.1.Micro` (AMD, 1 GB RAM;
> tendrías que añadir swap como en la guía de Azure).

## 3. Abrir puertos — ¡en DOS sitios! (el fallo típico de Oracle)
**a) Firewall de la nube (VCN):** Networking → tu VCN → Security Lists → *Default Security List*
→ **Add Ingress Rules**: para TCP **80** y **443**, Source `0.0.0.0/0`. (El 22/SSH ya viene abierto.)

**b) Firewall de la propia VM:** las imágenes Ubuntu de Oracle bloquean todo por iptables. Entra
por SSH y abre 80/443:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 4. Instalar Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

## 5. Clonar, configurar y arrancar
```bash
git clone https://github.com/palodo/PiScouting_V2.git
cd PiScouting_V2
cp .env.example .env
nano .env    # rellena PISCOUTING_SECRET, PISCOUTING_ADMIN_TOKEN, DOMAIN, FRONTEND_ORIGIN
docker compose up -d --build
curl -s http://127.0.0.1:8080/api/health     # {"status":"ok", ...}
```
La BBDD se siembra sola del dump la primera vez. Con dominio (registro **A** → IP de la VM),
Caddy saca el HTTPS solo; para probar sin dominio, pon `DOMAIN=:80` en el `.env`.

## 6. Actualización diaria (cron de la VM)
```bash
crontab -e
```
```
0 5 * * * curl -fsS -X POST http://127.0.0.1:8080/api/admin/refresh -H "X-Admin-Token: TU_ADMIN_TOKEN" >> /tmp/piscouting-refresh.log 2>&1
```

## 7. Conectar el frontend
Al construir la web, `VITE_API_BASE = https://api.tudominio.com` (o `http://LA_IP` sin dominio),
y ese dominio en `FRONTEND_ORIGIN` del `.env`.

## Operar
- Actualizar: `git pull && docker compose up -d --build`
- Logs: `docker compose logs -f`
- Backup BBDD: `docker compose cp app:/data/scouting.db ./backup_$(date +%F).db`
- **No definas `DATABASE_URL`** → usa el SQLite local del volumen.
