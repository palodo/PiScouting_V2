"""Notificaciones push (Web Push) a móviles y navegadores.

Los avisos ya existen en `fantasy_notifications`; esto solo los empuja al dispositivo.
El envío NO va dentro de la petición que crea el aviso, sino en un hilo aparte que cada
pocos segundos busca los que están sin empujar. Es a propósito:

  - Una tanda de mercado genera decenas de avisos: mandarlos en caliente dejaría al
    usuario esperando a que respondan los servidores de Apple y Google.
  - Si la transacción se deshace, el aviso no llega a existir y nadie recibe una mentira.
  - Y lo más importante: así también se empuja lo que crea el cron horario (la jornada
    que se puntúa sola), que no nace de ninguna petición.

Claves VAPID: se generan una vez en el servidor (`generate_keys`) y viven en el .env.
Sin ellas, todo esto queda desactivado y la app funciona igual, solo que sin push.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

from sqlmodel import Session, select

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
# Contacto que exige el estándar: a quién avisar si nuestros envíos dan problemas.
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:hola@pifantasy.com").strip()

SWEEP_SECONDS = 20        # cada cuánto se miran los avisos pendientes
MAX_FAILURES = 3          # rechazos seguidos antes de dar el dispositivo por muerto
MAX_AGE_MIN = 60          # un aviso más viejo que esto ya no se empuja: llegaría tarde


def enabled() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def generate_keys() -> tuple[str, str]:
    """Genera un par de claves VAPID (pública, privada) en base64url.

    Se llama a mano una sola vez, en el servidor, para no tener que pasar la privada
    por ningún sitio. Ver DEPLOY_AZURE.md.
    """
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_numbers().private_value.to_bytes(32, "big")
    pub = key.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return b64(pub), b64(priv)


def _send_one(sub, payload: dict) -> bool:
    """Manda un aviso a un dispositivo. False si hay que dar la suscripción por perdida."""
    from pywebpush import WebPushException, webpush
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            timeout=10,
        )
        return True
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        # 404/410: el navegador ya no existe (app desinstalada, permiso retirado)
        if code in (404, 410):
            return False
        print(f"[push] error {code} enviando a {sub.endpoint[:60]}…", flush=True)
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[push] fallo inesperado: {type(e).__name__}: {e}", flush=True)
        raise


def send_to_user(session: Session, user_id: int, title: str, body: str,
                 url: str = "/") -> int:
    """Empuja un aviso a todos los dispositivos de un usuario. Devuelve cuántos salieron."""
    from .models import PushSubscription
    if not enabled():
        return 0
    subs = session.exec(select(PushSubscription).where(
        PushSubscription.user_id == user_id)).all()
    enviados = 0
    for sub in subs:
        try:
            if _send_one(sub, {"title": title, "body": body, "url": url}):
                enviados += 1
                if sub.failures:
                    sub.failures = 0
                    session.add(sub)
            else:
                session.delete(sub)          # dispositivo muerto: fuera
        except Exception:
            sub.failures += 1
            session.add(sub)
            if sub.failures >= MAX_FAILURES:
                session.delete(sub)
    session.commit()
    return enviados


def _sweep(engine) -> int:
    """Empuja los avisos que aún no se han mandado. Devuelve cuántos se procesaron."""
    from datetime import datetime, timedelta

    from .models import FantasyNotification, FantasyMember
    with Session(engine) as session:
        corte = datetime.utcnow() - timedelta(minutes=MAX_AGE_MIN)
        pend = session.exec(select(FantasyNotification).where(
            FantasyNotification.pushed == False).order_by(  # noqa: E712
            FantasyNotification.id).limit(100)).all()
        if not pend:
            return 0
        for n in pend:
            # se marcan siempre, salgan o no: reintentar en bucle un aviso viejo no
            # ayuda a nadie y llenaría el registro de errores
            n.pushed = True
            session.add(n)
            if n.created_at < corte:
                continue
            m = session.get(FantasyMember, n.member_id)
            if not m:
                continue
            try:
                send_to_user(session, m.user_id, n.title, n.body or "", "/")
            except Exception as e:  # noqa: BLE001
                print(f"[push] no se pudo empujar el aviso {n.id}: {e}", flush=True)
        session.commit()
        return len(pend)


_hilo: Optional[threading.Thread] = None


def start_worker(engine) -> None:
    """Arranca el hilo de envío. Silencioso si no hay claves VAPID."""
    global _hilo
    if not enabled() or (_hilo and _hilo.is_alive()):
        return

    def bucle():
        while True:
            try:
                _sweep(engine)
            except Exception as e:  # noqa: BLE001 - el hilo no se puede morir
                print(f"[push] error en el barrido: {type(e).__name__}: {e}", flush=True)
            time.sleep(SWEEP_SECONDS)

    _hilo = threading.Thread(target=bucle, daemon=True, name="push-worker")
    _hilo.start()
    print("[push] hilo de notificaciones arrancado", flush=True)
