"""Clave del dueño: sin ella el chat solo consulta.

Se guarda en `.env` como hash scrypt con sal (`DUENO_CLAVE_HASH`), nunca en
claro. Se define con `uv run python acceso.py`.
"""

import getpass
import hashlib
import hmac
import os
import secrets
from pathlib import Path

ENV = Path(__file__).parent / ".env"
LARGO_MINIMO = 8
MAX_INTENTOS = 5


def hash_clave(clave: str, sal: str | None = None) -> str:
    sal = sal or secrets.token_hex(16)
    h = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal), n=2**14, r=8, p=1)
    return f"scrypt${sal}${h.hex()}"


def verificar_clave(clave: str, guardado: str | None = None) -> bool:
    guardado = guardado if guardado is not None else os.getenv("DUENO_CLAVE_HASH", "")
    try:
        algoritmo, sal, _ = guardado.split("$")
    except ValueError:
        return False
    if algoritmo != "scrypt" or not clave:
        return False
    return hmac.compare_digest(hash_clave(clave, sal), guardado)


def hay_clave() -> bool:
    return bool(os.getenv("DUENO_CLAVE_HASH"))


def guardar_en_env(valor: str, env: Path = ENV) -> None:
    lineas = env.read_text().splitlines() if env.exists() else []
    lineas = [l for l in lineas if not l.startswith("DUENO_CLAVE_HASH=")]
    lineas.append(f"DUENO_CLAVE_HASH={valor}")
    env.write_text("\n".join(lineas) + "\n")


if __name__ == "__main__":
    clave = getpass.getpass("Nueva clave del dueño: ")
    if len(clave) < LARGO_MINIMO:
        raise SystemExit(f"Minimo {LARGO_MINIMO} caracteres.")
    if getpass.getpass("Repitela: ") != clave:
        raise SystemExit("No coinciden.")
    guardar_en_env(hash_clave(clave))
    print("Guardada en .env (solo el hash). Reinicia la app.")
