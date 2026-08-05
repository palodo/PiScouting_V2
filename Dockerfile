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
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
