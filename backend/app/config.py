"""Configuración central del backend PiScouting."""
from __future__ import annotations

import os
from pathlib import Path

# Raíz del proyecto (PiScoutingv2/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Carga variables de PROJECT_ROOT/.env (sin dependencias). No pisa las ya definidas."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Clave para firmar los JWT. En producción, definir PISCOUTING_SECRET en el entorno o en .env.
SECRET_KEY = os.environ.get("PISCOUTING_SECRET", "dev-secret-piscouting-change-me")
TOKEN_TTL_DAYS = int(os.environ.get("PISCOUTING_TOKEN_TTL_DAYS", "30"))
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Base de datos. En local: SQLite (portable, sin servidor). En producción: define la variable
# de entorno DATABASE_URL (p.ej. la de Neon/Postgres) y la app la usa automáticamente.
DB_PATH = DATA_DIR / "scouting.db"


def _resolve_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{DB_PATH}"
    # Normaliza el esquema de Postgres al driver psycopg v3 que usa SQLAlchemy.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _resolve_db_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# Imagen de media pista para los mapas de tiro (heredada del proyecto original)
COURT_IMAGE = DATA_DIR / "basket_court_edited.png"

# Fuente de datos FEB
FEB_BASE = "https://baloncestoenvivo.feb.es"
LIVESTATS_API = "https://intrafeb.feb.es/LiveStats.API/api/v1"

# Temporada por defecto: 2025 => "2025/2026"
DEFAULT_SEASON = "2025"

# Competiciones disponibles para el fantasy.
# ⚠️ 3ª FEB (Liga EBA) PUEDE incluir jugadores MENORES de edad y no tenemos su fecha de
# nacimiento para excluirlos individualmente. Se habilita SOLO para uso privado / no publicado.
# ANTES DE PUBLICAR la app hay que ingerir fechas de nacimiento y excluir a los <18 (o quitar 3ª FEB).
FANTASY_COMPETITIONS = ("1ª FEB", "2ª FEB", "3ª FEB")

# Categorías FEB. El `code` de la URL /calendario/<slug>/<code>/<season> selecciona la
# competición a nivel global (el slug es cosmético). Verificado empíricamente:
#   code 1 -> 1ª FEB (grupo único) · code 2 -> 2ª FEB (Este/Oeste) · code 5 -> 3ª FEB (grupos regionales)
COMPETITIONS = {
    "1ª FEB": {"calendar_code": 1, "calendar_slug": "primerafeb"},
    "2ª FEB": {"calendar_code": 2, "calendar_slug": "segundafeb"},
    "3ª FEB": {"calendar_code": 5, "calendar_slug": "tercerafeb"},
}

# Pausa de cortesía por partido (el token es global, así que hay pocas peticiones)
REQUEST_PAUSE = 0.2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
