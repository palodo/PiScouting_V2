# Imagen del backend PiScouting para Fly.io (SQLite en volumen).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias primero (mejor caché de capas)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Código del backend + assets que necesita en runtime:
#  - basket_court_edited.png: pista para los mapas de tiro del PDF
#  - scouting.db.gz: dump con el que se siembra el volumen la primera vez
COPY backend ./backend
COPY data/basket_court_edited.png data/scouting.db.gz ./data/

WORKDIR /app/backend
EXPOSE 8080
# Dos procesos porque la VM tiene dos núcleos: con uno solo, la mitad de la máquina no se
# usaba. Medido antes de tocarlo: abrir ligas distintas daba ~15 pantallas por segundo, y
# el trabajo es de CPU (recalcular boxscores), justo lo que un segundo proceso reparte.
#
# Ojo si algún día se sube este número: el hilo que empuja las notificaciones corre en
# CADA proceso, y solo no manda avisos por duplicado porque los reclama de forma atómica
# (ver push._sweep). Cualquier otra tarea de fondo que se añada necesita la misma cautela.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080",      "--workers", "2"]
