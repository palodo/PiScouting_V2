"""Configuración central del backend PiScouting."""
from __future__ import annotations

import os
from pathlib import Path

# Clave para firmar los JWT. En producción, definir PISCOUTING_SECRET en el entorno.
SECRET_KEY = os.environ.get("PISCOUTING_SECRET", "dev-secret-piscouting-change-me")
TOKEN_TTL_DAYS = 30

# Raíz del proyecto (PiScoutingv2/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Base de datos SQLite (portable, sin servidor). Migrable a Postgres cambiando la URL.
DB_PATH = DATA_DIR / "scouting.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Imagen de media pista para los mapas de tiro (heredada del proyecto original)
COURT_IMAGE = DATA_DIR / "basket_court_edited.png"

# Fuente de datos FEB
FEB_BASE = "https://baloncestoenvivo.feb.es"
LIVESTATS_API = "https://intrafeb.feb.es/LiveStats.API/api/v1"

# Temporada por defecto: 2025 => "2025/2026"
DEFAULT_SEASON = "2025"

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
