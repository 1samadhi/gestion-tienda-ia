"""Tools de stock. Capa sin LLM: determinista, testeable.

Separacion de responsabilidades:
    consultar_stock, productos_bajo_minimo  -> solo lectura, cualquier agente
    registrar_venta, registrar_reposicion   -> escritura, solo el agente que corresponda
"""

import re
import unicodedata
from dataclasses import dataclass

from db import conectar


@dataclass
class Producto:
    id: int
    nombre: str
    categoria: str
    stock_actual: int
    stock_minimo: int
    precio_unitario: float
    proveedor_email: str

    @property
    def bajo_minimo(self) -> bool:
        return self.stock_actual <= self.stock_minimo


def _fila_a_producto(fila) -> Producto:
    return Producto(
        id=fila["id"],
        nombre=fila["nombre"],
        categoria=fila["categoria"],
        stock_actual=fila["stock_actual"],
        stock_minimo=fila["stock_minimo"],
        precio_unitario=fila["precio_unitario"],
        proveedor_email=fila["proveedor_email"],
    )


def _cantidad_valida(cantidad: int) -> None:
    # La tool la llena el LLM: el tipo lo valida pydantic, el signo no.
    # Sin esto, vender -5 sumaba 5 unidades y dejaba una "venta" negativa.
    if not isinstance(cantidad, int) or isinstance(cantidad, bool) or cantidad <= 0:
        raise ValueError(f"La cantidad debe ser un entero positivo, llego {cantidad!r}")


def consultar_stock(nombre_parcial: str = "") -> list[Producto]:
    """Busca productos por coincidencia parcial del nombre. Vacio = todos.

    `%` y `_` del texto se buscan literales: son comodines de LIKE, no del usuario."""
    patron = re.sub(r"([\\%_])", r"\\\1", nombre_parcial)
    with conectar() as con:
        filas = con.execute(
            "SELECT * FROM productos WHERE nombre LIKE ? ESCAPE '\\' ORDER BY nombre",
            (f"%{patron}%",),
        ).fetchall()
    return [_fila_a_producto(f) for f in filas]


def _plano(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.strip().lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def resolver_producto(referencia: str) -> Producto:
    """Convierte lo que escribe el LLM ("#2", "2", "taladro") en UN producto.

    Si no hay coincidencia o hay mas de una, falla con la lista de opciones:
    nunca adivina. Adivinar un id fue lo que repuso el Cuaderno cuando se
    pidio el Taladro."""
    ref = referencia.strip().lstrip("#").strip()
    productos = consultar_stock("")
    if ref.isdigit():
        encontrados = [p for p in productos if p.id == int(ref)]
    else:
        exactos = [p for p in productos if _plano(p.nombre) == _plano(ref)]
        encontrados = exactos or [p for p in productos if _plano(ref) in _plano(p.nombre)]
    if len(encontrados) == 1:
        return encontrados[0]
    opciones = ", ".join(f"#{p.id} {p.nombre}" for p in (encontrados or productos))
    motivo = "es ambiguo" if encontrados else "no existe"
    raise ValueError(f"El producto {referencia!r} {motivo}. Opciones: {opciones}")


def proveedores_registrados() -> set[str]:
    with conectar() as con:
        filas = con.execute(
            "SELECT DISTINCT lower(proveedor_email) AS e FROM productos WHERE proveedor_email IS NOT NULL"
        ).fetchall()
    return {f["e"] for f in filas}


def productos_bajo_minimo() -> list[Producto]:
    with conectar() as con:
        filas = con.execute(
            "SELECT * FROM productos WHERE stock_actual <= stock_minimo ORDER BY nombre"
        ).fetchall()
    return [_fila_a_producto(f) for f in filas]


def registrar_venta(producto_id: int, cantidad: int) -> Producto:
    """Descuenta stock. Falla si no alcanza (no permite stock negativo)."""
    _cantidad_valida(cantidad)
    with conectar() as con:
        fila = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if fila is None:
            raise ValueError(f"No existe el producto {producto_id}")
        if fila["stock_actual"] < cantidad:
            raise ValueError(
                f"Stock insuficiente: hay {fila['stock_actual']}, se pidieron {cantidad}"
            )

        con.execute(
            "UPDATE productos SET stock_actual = stock_actual - ? WHERE id = ?",
            (cantidad, producto_id),
        )
        con.execute(
            "INSERT INTO movimientos (producto_id, tipo, cantidad) VALUES (?, 'venta', ?)",
            (producto_id, cantidad),
        )
        fila = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    return _fila_a_producto(fila)


def registrar_reposicion(producto_id: int, cantidad: int) -> Producto:
    """Suma stock, por ejemplo cuando llega un pedido del proveedor."""
    _cantidad_valida(cantidad)
    with conectar() as con:
        fila = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if fila is None:
            raise ValueError(f"No existe el producto {producto_id}")

        con.execute(
            "UPDATE productos SET stock_actual = stock_actual + ? WHERE id = ?",
            (cantidad, producto_id),
        )
        con.execute(
            "INSERT INTO movimientos (producto_id, tipo, cantidad) VALUES (?, 'ingreso', ?)",
            (producto_id, cantidad),
        )
        fila = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    return _fila_a_producto(fila)


def historial_producto(producto_id: int, limite: int = 10) -> list[dict]:
    """Memoria de largo plazo del dominio: los movimientos ya quedan en
    SQLite, persistentes entre sesiones. No hace falta un vector store
    para esto — la pregunta tipica ("cuanto se vendio este mes") es una
    consulta estructurada, no una busqueda semantica de texto libre.

    Orden por `id DESC` ademas de `fecha DESC`: dos movimientos en el
    mismo segundo (resolucion de `datetime('now')` en SQLite) quedarian
    en orden de insercion si solo se ordenara por fecha.
    """
    with conectar() as con:
        filas = con.execute(
            """SELECT tipo, cantidad, fecha FROM movimientos
               WHERE producto_id = ? ORDER BY fecha DESC, id DESC LIMIT ?""",
            (producto_id, limite),
        ).fetchall()
    return [dict(f) for f in filas]
