"""Autenticación: hash de contraseñas (PBKDF2, stdlib) y JWT."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import requests
from fastapi import Depends, HTTPException, Header
from sqlmodel import Session, select

from .config import SECRET_KEY, TOKEN_TTL_DAYS, ADMIN_EMAILS, GOOGLE_CLIENT_ID
from .db import get_session
from .models import User


def is_admin(user: Optional[User]) -> bool:
    return bool(user and user.email and user.email.lower() in ADMIN_EMAILS)


def verify_google_token(id_token: str) -> Optional[dict]:
    """Valida un ID token de Google y devuelve {email, name} si es válido para nuestra app."""
    if not GOOGLE_CLIENT_ID or not id_token:
        return None
    try:
        r = requests.get("https://oauth2.googleapis.com/tokeninfo",
                         params={"id_token": id_token}, timeout=8)
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("aud") != GOOGLE_CLIENT_ID:
            return None
        if str(d.get("email_verified")).lower() not in ("true", "1"):
            return None
        email = (d.get("email") or "").lower()
        if not email:
            return None
        return {"email": email, "name": d.get("name")}
    except Exception:
        return None

RESET_TTL_MIN = 30  # lo que dura un enlace de cambio de contraseña


def new_reset_token() -> tuple[str, str]:
    """Devuelve (token para el enlace, hash para guardar). El token no se guarda nunca."""
    import secrets
    token = secrets.token_urlsafe(32)
    return token, hash_reset_token(token)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2$sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, rounds, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "No autenticado")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Token inválido o expirado")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(401, "Usuario no encontrado")
    return user
