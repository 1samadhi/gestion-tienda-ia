"""Acciones que esperan la aprobacion del dueño (ASI09 / LLM03:2026).

El LLM propone; una persona decide. Reponer stock o escribirle a un
proveedor no se ejecuta desde una tool: queda aqui hasta que alguien aprieta
"Aprobar" en la app. Aprobar es Python puro, sin LLM.
"""

from typing import Callable

from db import ESQUEMA, conectar
from stock import registrar_reposicion


def _tabla() -> None:
    with conectar() as con:
        con.executescript(ESQUEMA)


def proponer_reposicion(producto_id: int, cantidad: int) -> int:
    _tabla()
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO operaciones_pendientes (tipo, producto_id, cantidad) VALUES ('reposicion', ?, ?)",
            (producto_id, cantidad),
        )
        return cur.lastrowid


def proponer_correo(destinatario: str, asunto: str, cuerpo: str) -> int:
    _tabla()
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO operaciones_pendientes (tipo, destinatario, asunto, cuerpo) VALUES ('correo', ?, ?, ?)",
            (destinatario, asunto, cuerpo),
        )
        return cur.lastrowid


def listar(estado: str = "pendiente") -> list[dict]:
    _tabla()
    with conectar() as con:
        filas = con.execute(
            """SELECT o.*, p.nombre AS producto FROM operaciones_pendientes o
               LEFT JOIN productos p ON p.id = o.producto_id
               WHERE o.estado = ? ORDER BY o.id""",
            (estado,),
        ).fetchall()
    return [dict(f) for f in filas]


def _cerrar(op_id: int, estado: str, resultado: str) -> None:
    with conectar() as con:
        con.execute(
            "UPDATE operaciones_pendientes SET estado = ?, resultado = ? WHERE id = ?",
            (estado, resultado, op_id),
        )


def _pendiente(op_id: int) -> dict:
    _tabla()
    with conectar() as con:
        fila = con.execute("SELECT * FROM operaciones_pendientes WHERE id = ?", (op_id,)).fetchone()
    if fila is None or fila["estado"] != "pendiente":
        raise ValueError(f"La operacion {op_id} no existe o ya fue resuelta")
    return dict(fila)


def aprobar(op_id: int, enviar_correo: Callable[[str, str, str], str]) -> str:
    op = _pendiente(op_id)
    if op["tipo"] == "reposicion":
        p = registrar_reposicion(op["producto_id"], op["cantidad"])
        resultado = f"{p.nombre} queda en {p.stock_actual} unidades"
    else:
        resultado = f"correo enviado, id={enviar_correo(op['destinatario'], op['asunto'], op['cuerpo'])}"
    _cerrar(op_id, "aprobada", resultado)
    return resultado


def descartar(op_id: int) -> None:
    _pendiente(op_id)
    _cerrar(op_id, "descartada", "descartada por el dueño")
