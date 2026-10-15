"""Autenticacion con Gmail. Se corre una sola vez.

Abre el navegador del sistema para el login de Google. Tras aceptar, guarda
el token en gmail_token.json y las siguientes corridas lo reusan sin volver
a pedir login.

Uso:
    uv run python autenticar_gmail.py
"""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

RAIZ = Path(__file__).parent
CREDENCIALES = RAIZ / "credentials.json"
TOKEN = RAIZ / "gmail_token.json"

# gmail.send alcanza para que el agente de compras redacte y envie el
# correo de reposicion; no se pide lectura del buzon.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> None:
    if not CREDENCIALES.exists():
        raise SystemExit(f"Falta {CREDENCIALES.name} (descargado de Google Cloud Console)")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENCIALES), SCOPES)
    credenciales = flow.run_local_server(port=0)

    TOKEN.write_text(credenciales.to_json())
    print(f"Listo. Token guardado en {TOKEN.name}")


if __name__ == "__main__":
    main()
