"""Esquema de base de datos para gestion de stock.

Generico: no asume rubro. Sirve para ferreteria, almacen, libreria, etc.
"""

import sqlite3
from pathlib import Path

RAIZ = Path(__file__).parent
DB = RAIZ / "tienda.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    categoria TEXT,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 0,
    precio_unitario REAL NOT NULL DEFAULT 0,
    proveedor_email TEXT
);

CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('venta', 'ingreso', 'ajuste')),
    cantidad INTEGER NOT NULL,
    fecha TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def crear_esquema() -> None:
    with conectar() as con:
        con.executescript(ESQUEMA)


def sembrar_datos_demo() -> None:
    """Datos de ejemplo, genericos. Reemplazables por cualquier rubro."""
    productos = [
        ("Cuaderno universitario", "Papeleria", 40, 10, 1500, "proveedor1@example.com"),
        ("Taladro percutor", "Herramientas", 3, 5, 45000, "proveedor2@example.com"),
        ("Pan de molde", "Almacen", 12, 15, 2200, "proveedor1@example.com"),
        ("Destornillador phillips", "Herramientas", 20, 8, 2500, "proveedor2@example.com"),
    ]
    with conectar() as con:
        con.executemany(
            """INSERT INTO productos
               (nombre, categoria, stock_actual, stock_minimo, precio_unitario, proveedor_email)
               VALUES (?, ?, ?, ?, ?, ?)""",
            productos,
        )


if __name__ == "__main__":
    crear_esquema()
    con = conectar()
    vacio = con.execute("SELECT COUNT(*) AS n FROM productos").fetchone()["n"] == 0
    con.close()
    if vacio:
        sembrar_datos_demo()
        print("Esquema creado y datos de demo cargados.")
    else:
        print("Esquema ya existia, datos intactos.")
