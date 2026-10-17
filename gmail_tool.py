"""Herramienta de envio de correo para el agente de compras.

Usa el token de autenticar_gmail.py. No pide credenciales por si solo:
si no hay token valido, falla con instrucciones.
"""

import base64
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

RAIZ = Path(__file__).parent
TOKEN = RAIZ / "gmail_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _servicio():
    if not TOKEN.exists():
        raise RuntimeError("Falta gmail_token.json. Corre: uv run python autenticar_gmail.py")

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> str:
    """Envia un correo y devuelve el id del mensaje enviado."""
    mensaje = MIMEText(cuerpo)
    mensaje["to"] = destinatario
    mensaje["subject"] = asunto

    crudo = base64.urlsafe_b64encode(mensaje.as_bytes()).decode()
    enviado = _servicio().users().messages().send(
        userId="me", body={"raw": crudo}
    ).execute()
    return enviado["id"]


if __name__ == "__main__":
    # Prueba manual: se manda el correo a si mismo para no depender de un
    # proveedor real todavia.
    import json

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    propio = json.loads(TOKEN.read_text()).get("client_id", "")

    id_msg = enviar_correo(
        destinatario="byismaeeldev@gmail.com",
        asunto="Prueba — agente de compras",
        cuerpo="Si llega este correo, el envio por Gmail funciona.",
    )
    print(f"Enviado. id={id_msg}")
