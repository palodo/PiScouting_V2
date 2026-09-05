"""Envío de correo por SMTP, con `smtplib` de la biblioteca estándar.

No hay librerías ni servicios propietarios: cualquier proveedor con SMTP vale (Brevo,
Gmail con contraseña de aplicación, el de tu hosting...). Si no hay configuración, el
envío se desactiva solo y el flujo sigue funcionando en modo "enlace de administrador":
por eso `send()` devuelve un booleano en vez de reventar.

Variables de entorno:
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD
    SMTP_FROM       remitente ("PiFantasy <hola@pifantasy.com>"); por defecto SMTP_USER
    APP_URL         base para los enlaces de los correos (https://pifantasy.com)
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER
APP_URL = os.environ.get("APP_URL", "https://pifantasy.com").rstrip("/")


def enabled() -> bool:
    """¿Está el correo configurado? Si no, quien llame debe ofrecer otra salida."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM)


def _from_header() -> str:
    name, addr = parseaddr(SMTP_FROM)
    return formataddr((name or "PiFantasy", addr or SMTP_FROM))


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Manda un correo. Devuelve si salió; nunca lanza excepción hacia arriba.

    Un fallo de SMTP no puede tumbar una petición de la API: el usuario ya ha hecho lo
    que tenía que hacer y el aviso siempre puede volver a pedirse.
    """
    if not enabled():
        return False
    msg = EmailMessage()
    msg["From"] = _from_header()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15,
                                  context=ssl.create_default_context()) as s:
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 - se registra y se sigue
        print(f"[mailer] no se pudo enviar a {to}: {type(e).__name__}: {e}", flush=True)
        return False


def send_password_reset(to: str, link: str, minutes: int) -> bool:
    texto = (
        "Has pedido cambiar tu contraseña de PiFantasy.\n\n"
        f"Entra aquí para poner una nueva:\n{link}\n\n"
        f"El enlace caduca en {minutes} minutos y solo sirve una vez.\n"
        "Si no has sido tú, ignora este correo: tu contraseña no ha cambiado.\n"
    )
    html = f"""<!doctype html><html><body style="margin:0;background:#f3f5f9;padding:28px 16px;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#0d1524">
<div style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #e4e8f0;
border-radius:16px;padding:28px">
  <div style="font-weight:800;font-size:19px;letter-spacing:-.02em;margin-bottom:18px">
    Pi<span style="color:#e85c14">Fantasy</span></div>
  <h1 style="font-size:20px;margin:0 0 12px">Cambiar tu contraseña</h1>
  <p style="color:#4f5c72;line-height:1.6;margin:0 0 22px">
    Has pedido cambiar tu contraseña. Pulsa el botón y podrás poner una nueva.</p>
  <a href="{link}" style="display:inline-block;background:#e85c14;color:#fff;font-weight:700;
     text-decoration:none;padding:13px 22px;border-radius:12px">Poner una contraseña nueva</a>
  <p style="color:#808da3;font-size:13px;line-height:1.6;margin:22px 0 0">
    El enlace caduca en {minutes} minutos y solo sirve una vez.<br>
    Si no has sido tú, ignora este correo: tu contraseña no ha cambiado.</p>
</div></body></html>"""
    return send(to, "Cambiar tu contraseña de PiFantasy", texto, html)
